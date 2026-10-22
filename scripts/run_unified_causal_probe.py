from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from src.config import get_settings
from src.domain.job import RawJobDocument
from src.domain.unified_jd import (
    UnifiedJDModelOutput,
    validate_unified_fact_clause_granularity,
    validate_unified_jd_evidence,
)
from src.evaluation.unified_metrics import evaluate_unified_manifest
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionRecord,
)
from src.infrastructure.llm_client import (
    ChatMessage,
    ModelClientError,
    StructuredModelRequest,
    StructuredModelResponse,
    create_structured_model_client,
)
from src.services.unified_jd_parser import UnifiedJDParser

DEFAULT_MANIFEST = Path(
    "artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-causal-probe-v1-2026-09-04.json"
)
DEFAULT_REPORT = Path(
    "artifacts/evaluation/unified-jd-causal-probe-report-v1-2026-09-04.json"
)
DEFAULT_CASE_IDS = (
    "campus-ai-069",
    "campus-ai-085",
    "campus-ai-091",
    "campus-ai-072",
    "campus-ai-011",
)
VARIANTS = ("current_v2", "without_text_fact_alignment")

# This is the only prompt fragment removed by the ablation. The surrounding
# request, JSON schema, model settings, raw JD, and validation remain unchanged.
TEXT_FACT_ALIGNMENT_FRAGMENT = (
    "education_requirements 和 major_requirements 必须按一个语义"
    "原子一个数组项；对应 fact clause 必须原样复用 facts 中完全相同的字符串，"
    "不得在 facts 中合并、在 clause 中拆分。例如专业范围必须同时写成 facts."
    'major_requirements=["计算机","软件工程","相关专业"] 和 clause.items='
    '["计算机","软件工程","相关专业"]，不能把 facts 写成'
    '["计算机、软件工程等相关专业"]。\n'
)

CASE_RATIONALES = {
    "campus-ai-069": "current v2 emits an integer graduation-year clause item",
    "campus-ai-085": "integer item, invalid experience enum, and omitted duties",
    "campus-ai-091": "singleton any_of clauses and invalid experience enum",
    "campus-ai-072": "schema-valid output with non-localizable evidence",
    "campus-ai-011": "schema-valid output that omitted all responsibilities",
}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _variant_request(
    parser: UnifiedJDParser,
    document: RawJobDocument,
    variant: str,
) -> StructuredModelRequest:
    request = parser.build_request(document)
    if variant == "current_v2":
        return request
    if variant != "without_text_fact_alignment":
        raise ValueError(f"unknown variant: {variant}")

    system_message = request.messages[0]
    occurrences = system_message.content.count(TEXT_FACT_ALIGNMENT_FRAGMENT)
    if occurrences != 1:
        raise ValueError(
            "expected exactly one text-fact alignment prompt fragment, "
            f"found {occurrences}"
        )
    ablated = system_message.content.replace(TEXT_FACT_ALIGNMENT_FRAGMENT, "")
    return request.model_copy(
        update={
            "messages": [
                ChatMessage(role="system", content=ablated),
                *request.messages[1:],
            ],
            "prompt_version": "causal-probe-without-text-fact-alignment-v1",
        }
    )


def _request_metadata(request: StructuredModelRequest) -> dict[str, Any]:
    system_prompt = request.messages[0].content
    serialized = _canonical_json(request.model_dump(mode="json"))
    return {
        "prompt_version": request.prompt_version,
        "system_prompt_sha256": _sha256_text(system_prompt),
        "system_prompt_chars": len(system_prompt),
        "schema_sha256": _sha256_text(_canonical_json(request.json_schema)),
        "request_sha256": _sha256_text(serialized),
    }


def _response_metadata(response: StructuredModelResponse) -> dict[str, Any]:
    return {
        **response.diagnostics,
        "model": response.model,
        "provider": response.provider,
        "response_id": response.response_id,
        "finish_reason": response.finish_reason,
        "request_duration_ms": response.request_duration_ms,
        "usage": response.usage,
    }


def _validate_output(
    output: dict[str, Any] | None,
    raw_content: str,
) -> dict[str, Any]:
    if output is None:
        return {
            "schema_valid": False,
            "granularity_valid": False,
            "evidence_valid": False,
            "parse_success": False,
            "validation_errors": [],
        }
    try:
        structured = UnifiedJDModelOutput.model_validate(output)
    except ValidationError as error:
        return {
            "schema_valid": False,
            "granularity_valid": False,
            "evidence_valid": False,
            "parse_success": False,
            "validation_errors": [
                {
                    "location": list(item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ],
        }

    granularity_valid = True
    evidence_valid = True
    validation_errors: list[dict[str, Any]] = []
    try:
        validate_unified_fact_clause_granularity(structured)
    except ValueError as error:
        granularity_valid = False
        validation_errors.append(
            {"stage": "granularity", "message": str(error)}
        )
    try:
        validate_unified_jd_evidence(structured, raw_content)
    except ValueError as error:
        evidence_valid = False
        validation_errors.append({"stage": "evidence", "message": str(error)})
    return {
        "schema_valid": True,
        "granularity_valid": granularity_valid,
        "evidence_valid": evidence_valid,
        "parse_success": granularity_valid and evidence_valid,
        "validation_errors": validation_errors,
    }


async def _run_one(
    *,
    parser: UnifiedJDParser,
    client: Any,
    case: Any,
    variant: str,
    repetition: int,
    response_format: str,
) -> dict[str, Any]:
    document = RawJobDocument(
        source_url=case.source.source_url,
        source_type="unified_causal_probe",
        raw_content=case.raw_content,
    )
    request = _variant_request(parser, document, variant)
    started = perf_counter()
    try:
        response = await client.generate(request)
    except ModelClientError as error:
        return {
            "case_id": case.id,
            "variant": variant,
            "repetition": repetition,
            "response_format": response_format,
            "request": _request_metadata(request),
            "output": None,
            "failure_code": error.code,
            "validation": _validate_output(None, case.raw_content),
            "diagnostics": {
                "model_error": str(error),
                **error.details,
                "case_duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        }

    validation = _validate_output(response.output, case.raw_content)
    return {
        "case_id": case.id,
        "variant": variant,
        "repetition": repetition,
        "response_format": response_format,
        "request": _request_metadata(request),
        "output": response.output,
        "failure_code": (
            None if validation["parse_success"] else "unified_output_invalid"
        ),
        "validation": validation,
        "diagnostics": {
            **_response_metadata(response),
            "case_duration_ms": round((perf_counter() - started) * 1000, 2),
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _normalized_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"\s+", " ", normalized)


def _dict_clause_signature(clause: dict[str, Any], mode: str) -> tuple[Any, ...]:
    qualifier = clause.get("qualifier")
    qualifier_signature = None
    if isinstance(qualifier, dict):
        qualifier_signature = (
            qualifier.get("experience_type"),
            qualifier.get("minimum_months"),
            _normalized_text(qualifier["domain"])
            if qualifier.get("domain")
            else None,
        )
    items = tuple(
        sorted(_normalized_text(item) for item in clause.get("items") or [])
    )
    if mode == "category_level_relation":
        return (
            clause.get("category"),
            clause.get("level"),
            clause.get("relation"),
        )
    if mode == "items":
        return (
            clause.get("category"),
            clause.get("fact_field"),
            clause.get("level"),
            clause.get("relation"),
            items,
        )
    if mode != "full":
        raise ValueError(f"unknown signature mode: {mode}")
    return (
        clause.get("category"),
        clause.get("fact_field"),
        clause.get("level"),
        clause.get("relation"),
        items,
        tuple(
            sorted(
                _normalized_text(item)
                for item in clause.get("examples") or []
            )
        ),
        bool(clause.get("allow_other")),
        qualifier_signature,
    )


def _raw_clause_metric(
    records: list[dict[str, Any]],
    cases_by_id: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    tp = 0
    fp = 0
    fn = 0
    for record in records:
        expected = Counter(
            _dict_clause_signature(clause.model_dump(mode="json"), mode)
            for clause in cases_by_id[record["case_id"]].expected.clauses
        )
        output = record.get("output") or {}
        predicted = Counter(
            _dict_clause_signature(clause, mode)
            for clause in output.get("clauses", [])
        )
        tp += sum((expected & predicted).values())
        fp += sum((predicted - expected).values())
        fn += sum((expected - predicted).values())
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _raw_fact_values(value: Any, field_name: str) -> set[str]:
    if value is None:
        return set()
    values = value if isinstance(value, list) else [value]
    normalized = {_normalized_text(item) for item in values if item is not None}
    if field_name == "locations":
        return {item.removesuffix("市") for item in normalized}
    return normalized


def _raw_fact_metrics(
    records: list[dict[str, Any]],
    cases_by_id: dict[str, Any],
) -> dict[str, Any]:
    field_names = (
        "job_type",
        "locations",
        "graduation_years",
        "education_requirements",
        "major_requirements",
        "internship_duration_months",
        "weekly_days",
        "earliest_start_date",
        "deadline",
    )
    fields: dict[str, Any] = {}
    for field_name in field_names:
        tp = 0
        fp = 0
        fn = 0
        for record in records:
            expected_value = getattr(
                cases_by_id[record["case_id"]].expected.facts,
                field_name,
            )
            output_facts = (record.get("output") or {}).get("facts") or {}
            expected = _raw_fact_values(expected_value, field_name)
            predicted = _raw_fact_values(output_facts.get(field_name), field_name)
            tp += len(expected & predicted)
            fp += len(predicted - expected)
            fn += len(expected - predicted)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        fields[field_name] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "fields": fields,
        "macro_f1": sum(item["f1"] for item in fields.values()) / len(fields),
    }


def _text_fact_alignment_summary(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    fields = ("education_requirements", "major_requirements")
    passed_field_checks = 0
    calls_with_all_fields_aligned = 0
    by_field: dict[str, dict[str, int]] = {
        field_name: {"passed": 0, "total": 0} for field_name in fields
    }
    for record in records:
        output = record.get("output") or {}
        facts = output.get("facts") or {}
        clauses = output.get("clauses") or []
        call_results: list[bool] = []
        for field_name in fields:
            fact_values = _raw_fact_values(facts.get(field_name), field_name)
            clause_values = {
                str(item).strip().casefold()
                for clause in clauses
                if clause.get("fact_field") == field_name
                for item in clause.get("items") or []
            }
            aligned = fact_values == clause_values
            by_field[field_name]["total"] += 1
            by_field[field_name]["passed"] += aligned
            passed_field_checks += aligned
            call_results.append(aligned)
        calls_with_all_fields_aligned += all(call_results)
    return {
        "passed_field_checks": passed_field_checks,
        "total_field_checks": len(records) * len(fields),
        "calls_with_all_fields_aligned": calls_with_all_fields_aligned,
        "call_count": len(records),
        "by_field": by_field,
    }


def _official_metrics_by_repetition(
    records: list[dict[str, Any]],
    manifest: UnifiedEvaluationManifest,
    selected_ids: set[str],
) -> list[dict[str, Any]]:
    selected_manifest = manifest.model_copy(
        update={
            "cases": [case for case in manifest.cases if case.id in selected_ids]
        }
    )
    results: list[dict[str, Any]] = []
    for repetition in sorted({record["repetition"] for record in records}):
        repetition_records = [
            record for record in records if record["repetition"] == repetition
        ]
        predictions = [
            UnifiedPredictionRecord(
                case_id=record["case_id"],
                output=record["output"],
                failure_code=record["failure_code"],
                model_call_count=1,
                diagnostics=record["diagnostics"],
            )
            for record in repetition_records
        ]
        report = evaluate_unified_manifest(selected_manifest, predictions)
        results.append(
            {
                "repetition": repetition,
                "schema_valid_rate": report["metrics"]["schema_valid_rate"],
                "parse_success_rate": report["metrics"]["parse_success_rate"],
                "facts_macro_f1": report["metrics"]["facts_macro_f1"],
                "clause_full_signature_f1": report["metrics"][
                    "clause_type_relation_f1"
                ],
                "required_clause_recall": report["metrics"][
                    "required_clause_recall"
                ],
                "unsupported_critical_fact_count": report["metrics"][
                    "unsupported_critical_fact_count"
                ],
            }
        )
    return results


def _variant_summary(
    records: list[dict[str, Any]],
    manifest: UnifiedEvaluationManifest,
) -> dict[str, Any]:
    cases_by_id = {case.id: case for case in manifest.cases}
    failure_codes = Counter(
        record["failure_code"] or "success" for record in records
    )
    validation_error_types: Counter[str] = Counter()
    numeric_item_occurrences = 0
    calls_with_numeric_items = 0
    spurious_fact_clauses: Counter[str] = Counter()
    predicted_categories: Counter[str] = Counter()
    predicted_levels: Counter[str] = Counter()
    expected_categories: Counter[str] = Counter()
    expected_levels: Counter[str] = Counter()
    zero_responsibility_calls = 0

    for record in records:
        for error in record["validation"]["validation_errors"]:
            validation_error_types[error.get("type", error.get("stage", "other"))] += 1
        output = record.get("output") or {}
        clauses = output.get("clauses", [])
        numeric_in_call = 0
        for clause in clauses:
            predicted_categories[clause.get("category")] += 1
            predicted_levels[clause.get("level")] += 1
            fact_field = clause.get("fact_field")
            if fact_field in {"job_type", "locations"}:
                spurious_fact_clauses[fact_field] += 1
            for item in clause.get("items") or []:
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    numeric_item_occurrences += 1
                    numeric_in_call += 1
        calls_with_numeric_items += numeric_in_call > 0
        expected = cases_by_id[record["case_id"]].expected.clauses
        expected_categories.update(clause.category for clause in expected)
        expected_levels.update(clause.level for clause in expected)
        if any(clause.category == "responsibility" for clause in expected) and not any(
            clause.get("category") == "responsibility" for clause in clauses
        ):
            zero_responsibility_calls += 1

    prompt_tokens = [
        record["diagnostics"].get("usage", {}).get("prompt_tokens")
        for record in records
        if isinstance(record["diagnostics"].get("usage"), dict)
        and isinstance(
            record["diagnostics"].get("usage", {}).get("prompt_tokens"), int
        )
    ]
    completion_tokens = [
        record["diagnostics"].get("usage", {}).get("completion_tokens")
        for record in records
        if isinstance(record["diagnostics"].get("usage"), dict)
        and isinstance(
            record["diagnostics"].get("usage", {}).get("completion_tokens"), int
        )
    ]
    selected_ids = {record["case_id"] for record in records}
    first_request = records[0]["request"] if records else {}
    return {
        "call_count": len(records),
        "request_fingerprint": {
            "prompt_version": first_request.get("prompt_version"),
            "system_prompt_sha256": first_request.get("system_prompt_sha256"),
            "system_prompt_chars": first_request.get("system_prompt_chars"),
            "schema_sha256": first_request.get("schema_sha256"),
        },
        "schema_valid_count": sum(
            record["validation"]["schema_valid"] for record in records
        ),
        "parse_success_count": sum(
            record["validation"]["parse_success"] for record in records
        ),
        "failure_codes": dict(sorted(failure_codes.items())),
        "validation_error_types": dict(sorted(validation_error_types.items())),
        "calls_with_numeric_clause_items": calls_with_numeric_items,
        "numeric_clause_item_occurrences": numeric_item_occurrences,
        "spurious_fact_clauses": dict(sorted(spurious_fact_clauses.items())),
        "zero_responsibility_calls": zero_responsibility_calls,
        "category_counts": {
            "expected": dict(sorted(expected_categories.items())),
            "predicted": dict(sorted(predicted_categories.items())),
        },
        "level_counts": {
            "expected": dict(sorted(expected_levels.items())),
            "predicted": dict(sorted(predicted_levels.items())),
        },
        "usage": {
            "prompt_tokens": sum(prompt_tokens),
            "completion_tokens": sum(completion_tokens),
            "mean_prompt_tokens": (
                sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else None
            ),
            "mean_completion_tokens": (
                sum(completion_tokens) / len(completion_tokens)
                if completion_tokens
                else None
            ),
        },
        "text_fact_alignment": _text_fact_alignment_summary(records),
        "raw_fact_metrics": _raw_fact_metrics(records, cases_by_id),
        "raw_clause_metrics": {
            mode: _raw_clause_metric(records, cases_by_id, mode)
            for mode in ("category_level_relation", "items", "full")
        },
        "official_metrics_by_repetition": _official_metrics_by_repetition(
            records,
            manifest,
            selected_ids,
        ),
        "unique_output_count_by_case": {
            case_id: len(
                {
                    record["diagnostics"].get("content_sha256")
                    for record in records
                    if record["case_id"] == case_id
                    and record["diagnostics"].get("content_sha256")
                }
            )
            for case_id in sorted(selected_ids)
        },
    }


def _build_report(
    payload: dict[str, Any],
    manifest: UnifiedEvaluationManifest,
) -> dict[str, Any]:
    records = payload["records"]
    experimental = [record for record in records if record["variant"] in VARIANTS]
    summaries = {
        variant: _variant_summary(
            [record for record in experimental if record["variant"] == variant],
            manifest,
        )
        for variant in VARIANTS
    }
    paired: list[dict[str, Any]] = []
    for case_id in payload["case_ids"]:
        for repetition in range(1, payload["repetitions"] + 1):
            pair = {
                record["variant"]: record
                for record in experimental
                if record["case_id"] == case_id
                and record["repetition"] == repetition
            }
            paired.append(
                {
                    "case_id": case_id,
                    "repetition": repetition,
                    "current_v2_success": pair["current_v2"]["validation"][
                        "parse_success"
                    ],
                    "without_alignment_success": pair[
                        "without_text_fact_alignment"
                    ]["validation"]["parse_success"],
                    "current_v2_prompt_tokens": pair["current_v2"][
                        "diagnostics"
                    ].get("usage", {}).get("prompt_tokens"),
                    "without_alignment_prompt_tokens": pair[
                        "without_text_fact_alignment"
                    ]["diagnostics"].get("usage", {}).get("prompt_tokens"),
                }
            )
    schema_probe = next(
        (record for record in records if record["variant"] == "json_schema_probe"),
        None,
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
        "variants": summaries,
        "paired_results": paired,
        "json_schema_probe": schema_probe,
    }


async def _run(arguments: argparse.Namespace) -> int:
    manifest = UnifiedEvaluationManifest.model_validate_json(
        arguments.manifest.read_text(encoding="utf-8")
    )
    cases_by_id = {case.id: case for case in manifest.cases}
    missing = sorted(set(arguments.case_ids) - set(cases_by_id))
    if missing:
        raise ValueError(f"unknown case ids: {', '.join(missing)}")

    settings = get_settings()
    if settings.structured_model_provider.strip().lower() == "fake":
        raise ValueError("causal probe requires a real structured model provider")
    one_call_settings = settings.model_copy(update={"llm_max_retries": 0})
    client = create_structured_model_client(one_call_settings)
    parser = UnifiedJDParser(client, validation_retries=0)

    if arguments.output.exists():
        if not arguments.resume:
            raise FileExistsError(
                f"output already exists; pass --resume: {arguments.output}"
            )
        payload = json.loads(arguments.output.read_text(encoding="utf-8"))
    else:
        payload = {
            "experiment_version": "unified-jd-causal-probe-v1",
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
            "ablation": {
                "removed_fragment": TEXT_FACT_ALIGNMENT_FRAGMENT,
                "removed_fragment_sha256": _sha256_text(
                    TEXT_FACT_ALIGNMENT_FRAGMENT
                ),
            },
            "records": [],
        }

    completed = {
        (record["variant"], record["repetition"], record["case_id"])
        for record in payload["records"]
    }
    jobs = [
        (variant, repetition, cases_by_id[case_id])
        for variant in VARIANTS
        for repetition in range(1, arguments.repetitions + 1)
        for case_id in arguments.case_ids
        if (variant, repetition, case_id) not in completed
    ]
    semaphore = asyncio.Semaphore(arguments.concurrency)
    write_lock = asyncio.Lock()

    async def run_job(variant: str, repetition: int, case: Any) -> None:
        async with semaphore:
            record = await _run_one(
                parser=parser,
                client=client,
                case=case,
                variant=variant,
                repetition=repetition,
                response_format="json_object",
            )
        async with write_lock:
            payload["records"].append(record)
            payload["records"].sort(
                key=lambda item: (
                    item["variant"],
                    item["repetition"],
                    payload["case_ids"].index(item["case_id"]),
                )
            )
            _write_json(arguments.output, payload)
            print(
                "causal-probe "
                f"variant={variant} repetition={repetition} case={case.id} "
                f"failure={record['failure_code'] or 'none'}",
                flush=True,
            )

    await asyncio.gather(*(run_job(*job) for job in jobs))

    probe_key = ("json_schema_probe", 1, arguments.case_ids[0])
    if arguments.probe_json_schema and probe_key not in completed:
        schema_settings = settings.model_copy(
            update={"llm_max_retries": 0, "llm_response_format": "json_schema"}
        )
        schema_client = create_structured_model_client(schema_settings)
        schema_parser = UnifiedJDParser(schema_client, validation_retries=0)
        probe = await _run_one(
            parser=schema_parser,
            client=schema_client,
            case=cases_by_id[arguments.case_ids[0]],
            variant="current_v2",
            repetition=1,
            response_format="json_schema",
        )
        probe["variant"] = "json_schema_probe"
        payload["records"].append(probe)
        _write_json(arguments.output, payload)
        print(
            "causal-probe variant=json_schema_probe "
            f"case={probe['case_id']} failure={probe['failure_code'] or 'none'}",
            flush=True,
        )

    payload["finished_at"] = datetime.now(UTC).isoformat()
    _write_json(arguments.output, payload)
    report = _build_report(payload, manifest)
    if arguments.report.exists() and not arguments.resume:
        raise FileExistsError(
            f"report already exists; pass --resume: {arguments.report}"
        )
    _write_json(arguments.report, report)
    print(
        f"causal-probe complete calls={len(payload['records'])} "
        f"output={arguments.output} report={arguments.report}",
        flush=True,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small Unified JD causal probe")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--case-ids", nargs="+", default=list(DEFAULT_CASE_IDS))
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--probe-json-schema", action="store_true")
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    if arguments.repetitions < 1 or arguments.repetitions > 3:
        parser.error("--repetitions must be between 1 and 3")
    if arguments.concurrency < 1 or arguments.concurrency > 4:
        parser.error("--concurrency must be between 1 and 4")
    return arguments


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
