from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from scripts.run_unified_causal_probe import (
    CASE_RATIONALES,
    DEFAULT_CASE_IDS,
    DEFAULT_MANIFEST,
    _request_metadata,
    _response_metadata,
    _validate_output,
    _variant_summary,
    _write_json,
)
from src.config import get_settings
from src.domain.job import RawJobDocument
from src.domain.unified_jd_extraction import UnifiedJDExtractionV2
from src.evaluation.unified_metrics import evaluate_unified_manifest
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionRecord,
)
from src.infrastructure.llm_client import (
    ModelClientError,
    create_structured_model_client,
)
from src.services.unified_jd_extraction import (
    UNIFIED_EVIDENCE_LINE_EXTRACTOR_VERSION,
    UNIFIED_EXTRACTION_COMPILER_VERSION,
    compile_unified_extraction_v2,
)
from src.services.unified_jd_parser import (
    EXTRACTION_UNIFIED_PARSER_VERSION,
    EXTRACTION_UNIFIED_PROMPT_VERSION,
    UnifiedJDParser,
)

DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-extraction-probe-v1-2026-09-04.json"
)
DEFAULT_REPORT = Path(
    "artifacts/evaluation/unified-jd-extraction-probe-report-v1-2026-09-04.json"
)
DEFAULT_RECOMPILED_REPORT = Path(
    "artifacts/evaluation/"
    "unified-jd-extraction-probe-recompiled-report-v2-2026-09-04.json"
)
DEFAULT_BASELINE_REPORT = Path(
    "artifacts/evaluation/unified-jd-causal-probe-report-v1-2026-09-04.json"
)
MAX_MODEL_CALLS = 10


def _validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "location": list(item["loc"]),
            "message": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]


async def _run_one(
    *,
    parser: UnifiedJDParser,
    client: Any,
    case: Any,
    repetition: int,
) -> dict[str, Any]:
    document = RawJobDocument(
        source_url=case.source.source_url,
        source_type="unified_extraction_probe",
        raw_content=case.raw_content,
    )
    request = parser.build_request(document)
    started = perf_counter()
    try:
        response = await client.generate(request)
    except ModelClientError as error:
        return {
            "case_id": case.id,
            "repetition": repetition,
            "request": _request_metadata(request),
            "raw_output": None,
            "compiled_output": None,
            "model_contract_valid": False,
            "model_contract_validation_errors": [],
            "compilation_diagnostics": [],
            "failure_code": error.code,
            "validation": _validate_output(None, case.raw_content),
            "diagnostics": {
                "model_error": str(error),
                **error.details,
                "case_duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        }

    try:
        UnifiedJDExtractionV2.model_validate(response.output)
    except ValidationError as error:
        model_contract_valid = False
        model_contract_errors = _validation_errors(error)
    else:
        model_contract_valid = True
        model_contract_errors = []

    try:
        compilation = compile_unified_extraction_v2(
            response.output,
            case.raw_content,
        )
    except (TypeError, ValueError, ValidationError) as error:
        compiled_output = None
        compilation_diagnostics = [
            {
                "code": "compilation_failed",
                "path": "output",
                "message": str(error),
            }
        ]
        failure_code = "unified_output_invalid"
        validation = _validate_output(None, case.raw_content)
    else:
        compiled_output = compilation.output.model_dump(mode="json")
        compilation_diagnostics = [item.as_dict() for item in compilation.diagnostics]
        validation = _validate_output(compiled_output, case.raw_content)
        failure_code = None if validation["parse_success"] else "unified_output_invalid"

    return {
        "case_id": case.id,
        "repetition": repetition,
        "request": _request_metadata(request),
        "raw_output": response.output,
        "compiled_output": compiled_output,
        "model_contract_valid": model_contract_valid,
        "model_contract_validation_errors": model_contract_errors,
        "compilation_diagnostics": compilation_diagnostics,
        "failure_code": failure_code,
        "validation": validation,
        "diagnostics": {
            **_response_metadata(response),
            "case_duration_ms": round((perf_counter() - started) * 1000, 2),
        },
    }


def _baseline_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, Any] = {}
    for name, summary in report.get("variants", {}).items():
        result[name] = {
            "parse_success_count": summary.get("parse_success_count"),
            "facts_macro_f1": summary.get("raw_fact_metrics", {}).get("macro_f1"),
            "category_level_relation_f1": summary.get("raw_clause_metrics", {})
            .get("category_level_relation", {})
            .get("f1"),
            "full_clause_f1": summary.get("raw_clause_metrics", {})
            .get("full", {})
            .get("f1"),
            "zero_responsibility_calls": summary.get("zero_responsibility_calls"),
        }
    return result


def _build_report(
    payload: dict[str, Any],
    manifest: UnifiedEvaluationManifest,
    baseline_report: Path,
) -> dict[str, Any]:
    records = payload["records"]
    summary_records = [
        {
            **record,
            "output": record["compiled_output"],
        }
        for record in records
    ]
    summary = _variant_summary(summary_records, manifest)
    diagnostic_counts = Counter(
        item["code"] for record in records for item in record["compilation_diagnostics"]
    )
    return {
        "experiment_version": payload["experiment_version"],
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest": payload["manifest"],
        "model": payload["model"],
        "case_ids": payload["case_ids"],
        "case_rationales": payload["case_rationales"],
        "repetitions": payload["repetitions"],
        "new_model_call_count": len(records),
        "model_contract_valid_count": sum(
            record["model_contract_valid"] for record in records
        ),
        "compiled_success_count": sum(
            record["validation"]["parse_success"] for record in records
        ),
        "compilation_diagnostic_counts": dict(sorted(diagnostic_counts.items())),
        "compiled_summary": summary,
        "baseline_snapshot": _baseline_snapshot(baseline_report),
    }


def _compile_saved_record(
    record: dict[str, Any],
    *,
    source_content: str,
) -> dict[str, Any]:
    raw_output = record.get("raw_output")
    if raw_output is None:
        compiled_output = None
        compilation_diagnostics = [
            {
                "code": "raw_output_unavailable",
                "path": "raw_output",
                "message": "源实验没有保存可供离线重编译的原始响应",
            }
        ]
        failure_code = record.get("failure_code") or "unified_output_invalid"
        validation = _validate_output(None, source_content)
    else:
        try:
            compilation = compile_unified_extraction_v2(
                raw_output,
                source_content,
            )
        except (TypeError, ValueError, ValidationError) as error:
            compiled_output = None
            compilation_diagnostics = [
                {
                    "code": "compilation_failed",
                    "path": "raw_output",
                    "message": str(error),
                }
            ]
            failure_code = "unified_output_invalid"
            validation = _validate_output(None, source_content)
        else:
            compiled_output = compilation.output.model_dump(mode="json")
            compilation_diagnostics = [
                item.as_dict() for item in compilation.diagnostics
            ]
            validation = _validate_output(compiled_output, source_content)
            failure_code = (
                None if validation["parse_success"] else "unified_output_invalid"
            )

    return {
        "case_id": record["case_id"],
        "repetition": record["repetition"],
        "request": record.get("request", {}),
        "output": compiled_output,
        "failure_code": failure_code,
        "validation": validation,
        "diagnostics": record.get("diagnostics", {}),
        "compilation_diagnostics": compilation_diagnostics,
    }


def _diagnostic_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        item["code"] for record in records for item in record["compilation_diagnostics"]
    )
    return dict(sorted(counts.items()))


def _dimensional_evaluation_by_repetition(
    records: list[dict[str, Any]],
    manifest: UnifiedEvaluationManifest,
) -> list[dict[str, Any]]:
    selected_ids = {record["case_id"] for record in records}
    selected_manifest = manifest.model_copy(
        update={"cases": [case for case in manifest.cases if case.id in selected_ids]}
    )
    results: list[dict[str, Any]] = []
    for repetition in sorted({record["repetition"] for record in records}):
        repetition_records = [
            record for record in records if record["repetition"] == repetition
        ]
        report = evaluate_unified_manifest(
            selected_manifest,
            [
                UnifiedPredictionRecord(
                    case_id=record["case_id"],
                    output=record["output"],
                    failure_code=record["failure_code"],
                    model_call_count=1,
                    diagnostics=record["diagnostics"],
                )
                for record in repetition_records
            ],
        )
        results.append(
            {
                "repetition": repetition,
                "evaluation_version": report["evaluation_version"],
                "schema_valid_rate": report["schema_valid_rate"],
                "parse_success_rate": report["parse_success_rate"],
                "dimensions": report["dimensions"],
                "legacy_clause_exact": report["clauses"],
            }
        )
    return results


def _build_recompiled_report(
    payload: dict[str, Any],
    manifest: UnifiedEvaluationManifest,
    baseline_report: Path,
    source_path: Path,
) -> dict[str, Any]:
    cases_by_id = {case.id: case for case in manifest.cases}
    source_records = payload["records"]
    recorded_records = [
        {**record, "output": record.get("compiled_output")} for record in source_records
    ]
    recompiled_records = [
        _compile_saved_record(
            record,
            source_content=cases_by_id[record["case_id"]].raw_content,
        )
        for record in source_records
    ]
    result_rows = []
    for source_record, recompiled_record in zip(
        source_records,
        recompiled_records,
        strict=True,
    ):
        raw_output = source_record.get("raw_output")
        raw_sha256 = None
        if raw_output is not None:
            raw_sha256 = hashlib.sha256(
                json.dumps(
                    raw_output,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        result_rows.append(
            {
                "case_id": source_record["case_id"],
                "repetition": source_record["repetition"],
                "raw_output_sha256": raw_sha256,
                "model_contract_valid": source_record["model_contract_valid"],
                "recorded_parse_success": source_record["validation"]["parse_success"],
                "posthoc_parse_success": recompiled_record["validation"][
                    "parse_success"
                ],
                "compiled_output_changed": source_record.get("compiled_output")
                != recompiled_record["output"],
                "posthoc_compilation_diagnostics": recompiled_record[
                    "compilation_diagnostics"
                ],
            }
        )

    return {
        "report_version": "unified-jd-extraction-probe-recompiled-report-v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_experiment": {
            "path": source_path.as_posix(),
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "experiment_version": payload["experiment_version"],
        },
        "manifest": payload["manifest"],
        "model": payload["model"],
        "case_ids": payload["case_ids"],
        "case_rationales": payload["case_rationales"],
        "repetitions": payload["repetitions"],
        "new_model_call_count": 0,
        "source_model_call_count": len(source_records),
        "model_contract_valid_count": sum(
            record["model_contract_valid"] for record in source_records
        ),
        "recorded_compilation": {
            "provenance": "compiled_output stored during the source experiment",
            "compiled_success_count": sum(
                record["validation"]["parse_success"] for record in source_records
            ),
            "compilation_diagnostic_counts": _diagnostic_counts(source_records),
            "compiled_summary": _variant_summary(recorded_records, manifest),
        },
        "posthoc_recompilation": {
            "compiler_version": UNIFIED_EXTRACTION_COMPILER_VERSION,
            "compiled_success_count": sum(
                record["validation"]["parse_success"] for record in recompiled_records
            ),
            "compilation_diagnostic_counts": _diagnostic_counts(recompiled_records),
            "compiled_summary": _variant_summary(recompiled_records, manifest),
            "dimensional_evaluation_by_repetition": (
                _dimensional_evaluation_by_repetition(
                    recompiled_records,
                    manifest,
                )
            ),
        },
        "record_results": result_rows,
        "baseline_snapshot": _baseline_snapshot(baseline_report),
    }


async def _run(arguments: argparse.Namespace) -> int:
    manifest = UnifiedEvaluationManifest.model_validate_json(
        arguments.manifest.read_text(encoding="utf-8")
    )
    report_path = arguments.report or (
        DEFAULT_RECOMPILED_REPORT if arguments.recompile_only else DEFAULT_REPORT
    )
    if arguments.recompile_only:
        if not arguments.output.exists():
            raise FileNotFoundError(
                f"source experiment does not exist: {arguments.output}"
            )
        payload = json.loads(arguments.output.read_text(encoding="utf-8"))
        manifest_sha256 = hashlib.sha256(arguments.manifest.read_bytes()).hexdigest()
        if payload.get("manifest", {}).get("sha256") != manifest_sha256:
            raise ValueError("source experiment and manifest SHA-256 do not match")
        known_case_ids = {case.id for case in manifest.cases}
        unknown_case_ids = sorted(
            {
                record.get("case_id")
                for record in payload.get("records", [])
                if record.get("case_id") not in known_case_ids
            }
        )
        if unknown_case_ids:
            raise ValueError(
                "source experiment contains unknown case ids: "
                + ", ".join(repr(case_id) for case_id in unknown_case_ids)
            )
        if report_path.exists() and not arguments.resume:
            raise FileExistsError(
                f"report already exists; pass --resume: {report_path}"
            )
        report = _build_recompiled_report(
            payload,
            manifest,
            arguments.baseline_report,
            arguments.output,
        )
        _write_json(report_path, report)
        print(
            "extraction-probe offline-recompile complete "
            f"new_model_calls=0 records={len(payload['records'])} "
            f"source={arguments.output} report={report_path}",
            flush=True,
        )
        return 0

    cases_by_id = {case.id: case for case in manifest.cases}
    missing = sorted(set(arguments.case_ids) - set(cases_by_id))
    if missing:
        raise ValueError(f"unknown case ids: {', '.join(missing)}")
    planned_calls = len(arguments.case_ids) * arguments.repetitions
    if planned_calls > MAX_MODEL_CALLS:
        raise ValueError(
            f"extraction probe is capped at {MAX_MODEL_CALLS} model calls; "
            f"requested {planned_calls}"
        )

    settings = get_settings()
    hostname = urlparse(settings.llm_base_url or "").hostname
    if settings.structured_model_provider.strip().lower() == "fake":
        raise ValueError("extraction probe requires a real structured model provider")
    if hostname != "api.deepseek.com":
        raise ValueError(
            "extraction probe is authorized only for api.deepseek.com; "
            f"configured host is {hostname!r}"
        )
    one_call_settings = settings.model_copy(update={"llm_max_retries": 0})
    client = create_structured_model_client(one_call_settings)
    parser = UnifiedJDParser(
        client,
        validation_retries=0,
        mode="extraction_v2",
    )

    if arguments.output.exists():
        if not arguments.resume:
            raise FileExistsError(
                f"output already exists; pass --resume: {arguments.output}"
            )
        payload = json.loads(arguments.output.read_text(encoding="utf-8"))
    else:
        payload = {
            "experiment_version": "unified-jd-extraction-probe-v2",
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
            "manifest": {
                "path": arguments.manifest.as_posix(),
                "sha256": hashlib.sha256(arguments.manifest.read_bytes()).hexdigest(),
                "dataset_version": manifest.dataset_version,
            },
            "model": {
                "provider": settings.structured_model_provider,
                "name": client.model_name,
                "configured_response_format": settings.llm_response_format,
                "parser_mode": parser.mode,
                "parser_version": EXTRACTION_UNIFIED_PARSER_VERSION,
                "prompt_version": EXTRACTION_UNIFIED_PROMPT_VERSION,
                "evidence_line_extractor_version": (
                    UNIFIED_EVIDENCE_LINE_EXTRACTOR_VERSION
                ),
                "compiler_version": UNIFIED_EXTRACTION_COMPILER_VERSION,
                "validation_retries": 0,
                "transport_retries": 0,
                "concurrency": arguments.concurrency,
            },
            "case_ids": list(arguments.case_ids),
            "case_rationales": {
                case_id: CASE_RATIONALES.get(case_id, "user-selected case")
                for case_id in arguments.case_ids
            },
            "repetitions": arguments.repetitions,
            "records": [],
        }

    completed = {
        (record["repetition"], record["case_id"]) for record in payload["records"]
    }
    jobs = [
        (repetition, cases_by_id[case_id])
        for repetition in range(1, arguments.repetitions + 1)
        for case_id in arguments.case_ids
        if (repetition, case_id) not in completed
    ]
    if len(payload["records"]) + len(jobs) > MAX_MODEL_CALLS:
        raise ValueError("resume payload plus pending jobs exceeds the call cap")

    semaphore = asyncio.Semaphore(arguments.concurrency)
    write_lock = asyncio.Lock()

    async def run_job(repetition: int, case: Any) -> None:
        async with semaphore:
            record = await _run_one(
                parser=parser,
                client=client,
                case=case,
                repetition=repetition,
            )
        async with write_lock:
            payload["records"].append(record)
            payload["records"].sort(
                key=lambda item: (
                    item["repetition"],
                    payload["case_ids"].index(item["case_id"]),
                )
            )
            _write_json(arguments.output, payload)
            print(
                "extraction-probe "
                f"repetition={repetition} case={case.id} "
                f"failure={record['failure_code'] or 'none'}",
                flush=True,
            )

    await asyncio.gather(*(run_job(*job) for job in jobs))

    payload["finished_at"] = datetime.now(UTC).isoformat()
    _write_json(arguments.output, payload)
    report = _build_report(payload, manifest, arguments.baseline_report)
    if report_path.exists() and not arguments.resume:
        raise FileExistsError(f"report already exists; pass --resume: {report_path}")
    _write_json(report_path, report)
    print(
        f"extraction-probe complete calls={len(payload['records'])} "
        f"output={arguments.output} report={report_path}",
        flush=True,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the capped Unified JD extraction/compiler probe"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Report path. Defaults to the recorded report normally and the "
            "versioned posthoc report with --recompile-only."
        ),
    )
    parser.add_argument(
        "--baseline-report",
        type=Path,
        default=DEFAULT_BASELINE_REPORT,
    )
    parser.add_argument("--case-ids", nargs="+", default=list(DEFAULT_CASE_IDS))
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--recompile-only",
        action="store_true",
        help="Recompile saved raw outputs locally without creating a model client.",
    )
    arguments = parser.parse_args()
    if arguments.repetitions < 1 or arguments.repetitions > 2:
        parser.error("--repetitions must be 1 or 2")
    if arguments.concurrency < 1 or arguments.concurrency > 4:
        parser.error("--concurrency must be between 1 and 4")
    return arguments


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
