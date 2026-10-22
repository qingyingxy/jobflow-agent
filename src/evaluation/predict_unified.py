from __future__ import annotations

import argparse
import asyncio
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
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
    UnifiedPredictionRecord,
)
from src.infrastructure.llm_client import (
    ModelClientError,
    StructuredModelClient,
    StructuredModelResponse,
    create_structured_model_client,
)
from src.services.unified_jd_extraction import (
    compile_model_first_extraction_v3,
    compile_unified_extraction_v2,
)
from src.services.unified_jd_parser import UnifiedJDParser, UnifiedParserMode


async def generate_unified_predictions(
    manifest: UnifiedEvaluationManifest,
    *,
    client: StructuredModelClient,
    concurrency: int = 1,
    checkpoint_path: Path | None = None,
    resume: bool = False,
    max_new_cases: int | None = None,
    max_model_calls: int | None = None,
    stop_on_failure: bool = False,
    parser_mode: UnifiedParserMode = "frozen_v2",
    validation_retries: int = 0,
) -> UnifiedPredictionFile:
    """Generate predictions with resumable case and model-call budgets."""

    if manifest.label_status != "frozen" or any(
        case.annotation_status != "frozen" for case in manifest.cases
    ):
        raise ValueError("Unified predictions require a fully frozen manifest")
    if concurrency < 1 or concurrency > 4:
        raise ValueError("concurrency must be between 1 and 4")
    if max_new_cases is not None and max_new_cases < 1:
        raise ValueError("max_new_cases must be at least 1")
    if max_model_calls is not None and max_model_calls < 1:
        raise ValueError("max_model_calls must be at least 1")
    if validation_retries not in {0, 1}:
        raise ValueError("validation_retries must be 0 or 1")

    parser = UnifiedJDParser(
        client,
        validation_retries=validation_retries,
        mode=parser_mode,
    )
    generated_at = datetime.now(UTC).isoformat()
    predictions_by_id: dict[str, UnifiedPredictionRecord] = {}
    if resume:
        if checkpoint_path is None or not checkpoint_path.exists():
            raise ValueError("--resume requires an existing checkpoint")
        checkpoint = UnifiedPredictionFile.model_validate_json(
            checkpoint_path.read_text(encoding="utf-8")
        )
        _validate_checkpoint(
            checkpoint,
            manifest=manifest,
            parser=parser,
            client=client,
        )
        generated_at = checkpoint.generated_at or generated_at
        predictions_by_id = {
            prediction.case_id: prediction for prediction in checkpoint.predictions
        }

    model_calls_started = sum(
        prediction.model_call_count or 0 for prediction in predictions_by_id.values()
    )
    if max_model_calls is not None and model_calls_started > max_model_calls:
        raise ValueError(
            "checkpoint model calls exceed max_model_calls: "
            f"recorded={model_calls_started}, maximum={max_model_calls}"
        )
    model_call_lock = asyncio.Lock()

    async def reserve_model_call() -> bool:
        nonlocal model_calls_started
        async with model_call_lock:
            if max_model_calls is not None and model_calls_started >= max_model_calls:
                return False
            model_calls_started += 1
            return True

    pending_cases = [
        case for case in manifest.cases if case.id not in predictions_by_id
    ]
    if max_new_cases is not None:
        pending_cases = pending_cases[:max_new_cases]
    semaphore = asyncio.Semaphore(concurrency)

    async def run_case(case: Any) -> UnifiedPredictionRecord | None:
        async with semaphore:
            started = perf_counter()
            document = RawJobDocument(
                source_url=case.source.source_url,
                source_type="unified_evaluation",
                raw_content=case.raw_content,
            )
            request = parser.build_request(document)
            model_attempts: list[dict[str, Any]] = []
            record: UnifiedPredictionRecord | None = None
            for attempt in range(validation_retries + 1):
                if not await reserve_model_call():
                    break
                try:
                    response = await client.generate(request)
                except ModelClientError as error:
                    model_attempts.append(
                        {
                            "attempt": attempt + 1,
                            "failure_code": error.code,
                            "model_error": str(error),
                            **error.details,
                        }
                    )
                    record = UnifiedPredictionRecord(
                        case_id=case.id,
                        output=None,
                        failure_code=error.code,
                        model_call_count=attempt + 1,
                        diagnostics={
                            "model_error": str(error),
                            **error.details,
                            "model_attempts": model_attempts,
                        },
                    )
                    break

                if parser.mode in {
                    "extraction_v2",
                    "model_first_v1",
                    "model_first_v3",
                }:
                    failure_code, prediction_output, validation = (
                        _compile_extraction_output(
                            response.output,
                            raw_content=case.raw_content,
                            parser_mode=parser.mode,
                        )
                    )
                else:
                    failure_code, validation = _validate_raw_output(
                        response.output,
                        raw_content=case.raw_content,
                    )
                    prediction_output = response.output
                response_diagnostics = _response_diagnostics(response)
                model_attempts.append(
                    {
                        "attempt": attempt + 1,
                        "raw_model_output": response.output,
                        "failure_code": failure_code,
                        **response_diagnostics,
                        **validation,
                    }
                )
                record = UnifiedPredictionRecord(
                    case_id=case.id,
                    output=prediction_output,
                    failure_code=failure_code,
                    model_call_count=attempt + 1,
                    diagnostics={
                        **response_diagnostics,
                        **validation,
                        "model_attempts": model_attempts,
                    },
                )
                if failure_code is None:
                    break
                if attempt < validation_retries:
                    request = parser.build_repair_request(request, validation)

            if record is None:
                return None
            return record.model_copy(
                update={
                    "diagnostics": {
                        **record.diagnostics,
                        "input_sha256": case.source_content_sha256,
                        "validation_retries_allowed": validation_retries,
                        "case_duration_ms": round(
                            (perf_counter() - started) * 1000,
                            2,
                        ),
                    }
                }
            )

    def save_prediction(prediction: UnifiedPredictionRecord) -> None:
        predictions_by_id[prediction.case_id] = prediction
        if checkpoint_path is not None:
            _write_prediction_file(
                checkpoint_path,
                _prediction_file(
                    manifest=manifest,
                    predictions=predictions_by_id,
                    parser=parser,
                    client=client,
                    generated_at=generated_at,
                    checkpoint=True,
                ),
                immutable=False,
            )

    if stop_on_failure:
        for case in pending_cases:
            prediction = await run_case(case)
            if prediction is None:
                break
            save_prediction(prediction)
            if prediction.failure_code is not None:
                break
    else:
        tasks = [asyncio.create_task(run_case(case)) for case in pending_cases]
        for task in asyncio.as_completed(tasks):
            prediction = await task
            if prediction is not None:
                save_prediction(prediction)

    return _prediction_file(
        manifest=manifest,
        predictions=predictions_by_id,
        parser=parser,
        client=client,
        generated_at=generated_at,
        checkpoint=False,
    )


def _validate_raw_output(
    output: Any,
    *,
    raw_content: str,
) -> tuple[str | None, dict[str, Any]]:
    try:
        structured = UnifiedJDModelOutput.model_validate(output)
        validate_unified_fact_clause_granularity(structured)
        validate_unified_jd_evidence(structured, raw_content)
    except ValidationError as error:
        return "unified_output_invalid", {
            "validation_errors": [
                {
                    "location": list(item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ]
        }
    except ValueError as error:
        return "unified_output_invalid", {
            "validation_errors": [{"message": str(error)}]
        }
    return None, {}


def _compile_extraction_output(
    output: Any,
    *,
    raw_content: str,
    parser_mode: UnifiedParserMode,
) -> tuple[str | None, Any, dict[str, Any]]:
    try:
        compilation = (
            compile_model_first_extraction_v3(output, raw_content)
            if parser_mode == "model_first_v3"
            else compile_unified_extraction_v2(output, raw_content)
        )
    except ValidationError as error:
        return (
            "unified_output_invalid",
            output,
            {
                "raw_model_output": output,
                "validation_errors": [
                    {
                        "location": list(item["loc"]),
                        "message": item["msg"],
                        "type": item["type"],
                    }
                    for item in error.errors()
                ],
            },
        )
    except (TypeError, ValueError) as error:
        return (
            "unified_output_invalid",
            output,
            {
                "raw_model_output": output,
                "validation_errors": [{"message": str(error)}],
            },
        )
    return (
        None,
        compilation.output.model_dump(mode="json"),
        {
            "raw_model_output": output,
            "compilation_diagnostics": [
                item.as_dict() for item in compilation.diagnostics
            ],
        },
    )


def _response_diagnostics(response: StructuredModelResponse) -> dict[str, Any]:
    return {
        **response.diagnostics,
        "model": response.model,
        "provider": response.provider,
        "response_id": response.response_id,
        "finish_reason": response.finish_reason,
        "request_duration_ms": response.request_duration_ms,
        "usage": response.usage,
    }


def _prediction_file(
    *,
    manifest: UnifiedEvaluationManifest,
    predictions: dict[str, UnifiedPredictionRecord],
    parser: UnifiedJDParser,
    client: StructuredModelClient,
    generated_at: str,
    checkpoint: bool,
) -> UnifiedPredictionFile:
    ordered = [
        predictions[case.id] for case in manifest.cases if case.id in predictions
    ]
    prefix = "checkpoint" if checkpoint else "generated"
    return UnifiedPredictionFile(
        prediction_version=f"{prefix}-{manifest.dataset_version}",
        schema_version=parser.schema_version,
        parser_version=parser.parser_version,
        prompt_version=parser.prompt_version,
        model=client.model_name,
        generated_at=generated_at,
        predictions=ordered,
    )


def _validate_checkpoint(
    checkpoint: UnifiedPredictionFile,
    *,
    manifest: UnifiedEvaluationManifest,
    parser: UnifiedJDParser,
    client: StructuredModelClient,
) -> None:
    expected_metadata = {
        "schema_version": parser.schema_version,
        "parser_version": parser.parser_version,
        "prompt_version": parser.prompt_version,
        "model": client.model_name,
    }
    actual_metadata = {key: getattr(checkpoint, key) for key in expected_metadata}
    if actual_metadata != expected_metadata:
        raise ValueError(
            "checkpoint parser metadata mismatch: "
            f"expected={expected_metadata}, actual={actual_metadata}"
        )

    cases_by_id = {case.id: case for case in manifest.cases}
    for prediction in checkpoint.predictions:
        case = cases_by_id.get(prediction.case_id)
        if case is None:
            raise ValueError(f"checkpoint contains unknown case: {prediction.case_id}")
        if prediction.diagnostics.get("input_sha256") != (case.source_content_sha256):
            raise ValueError(f"checkpoint input hash mismatch: {prediction.case_id}")


def _write_prediction_file(
    path: Path,
    prediction_file: UnifiedPredictionFile,
    *,
    immutable: bool,
) -> None:
    rendered = prediction_file.model_dump_json(indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite changed file: {path}")
    path.write_text(rendered, encoding="utf-8")


def main() -> int:
    arguments = _parse_args()
    manifest = UnifiedEvaluationManifest.model_validate_json(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    settings = get_settings()
    if settings.structured_model_provider.strip().lower() == "fake" and not (
        arguments.allow_fake
    ):
        raise SystemExit(
            "正式 Unified 预测拒绝使用 fake provider；请配置真实模型，"
            "或仅在测试时显式传入 --allow-fake。"
        )

    one_request_settings = settings.model_copy(update={"llm_max_retries": 0})
    try:
        client = create_structured_model_client(one_request_settings)
    except ModelClientError as error:
        raise SystemExit(f"无法创建结构化模型客户端: {error}") from error

    previous_recorded_calls = _recorded_checkpoint_calls(
        Path(arguments.checkpoint) if arguments.resume else None
    )
    prediction_file = asyncio.run(
        generate_unified_predictions(
            manifest,
            client=client,
            concurrency=arguments.concurrency,
            checkpoint_path=Path(arguments.checkpoint),
            resume=arguments.resume,
            max_new_cases=arguments.max_new_cases,
            stop_on_failure=arguments.stop_on_failure,
            parser_mode=arguments.parser_mode,
            validation_retries=arguments.validation_retries,
        )
    )
    output_path = Path(arguments.output)
    _write_prediction_file(output_path, prediction_file, immutable=True)
    recorded_calls = sum(
        prediction.model_call_count or 0 for prediction in prediction_file.predictions
    )
    new_calls = recorded_calls - previous_recorded_calls
    validation_repairs = sum(
        max(0, (prediction.model_call_count or 0) - 1)
        for prediction in prediction_file.predictions
    )
    print(
        "unified predictions generated "
        f"cases={len(prediction_file.predictions)} "
        f"new_model_calls={new_calls} recorded_model_calls={recorded_calls} "
        f"validation_repairs={validation_repairs} transport_retries=0 "
        f"model={client.model_name} output={output_path}"
    )
    return 0


def _recorded_checkpoint_calls(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    checkpoint = UnifiedPredictionFile.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    return sum(
        prediction.model_call_count or 0 for prediction in checkpoint.predictions
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate resumable predictions for a frozen Unified manifest"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--concurrency", type=int, default=1, choices=(1, 2, 3, 4))
    parser.add_argument(
        "--max-new-cases",
        type=int,
        default=None,
        help="Run only the next N cases not already present in the checkpoint.",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop before calling another case after the first failed prediction.",
    )
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="Only for local runner tests; formal metrics must use a real provider.",
    )
    parser.add_argument(
        "--parser-mode",
        choices=(
            "frozen_v2",
            "extraction_v2",
            "model_first_v1",
            "model_first_v3",
        ),
        default="frozen_v2",
        help="Select the frozen direct-output parser or the opt-in local compiler path.",
    )
    parser.add_argument(
        "--validation-retries",
        type=int,
        choices=(0, 1),
        default=0,
        help="Allow at most one extra model call to repair invalid JSON or evidence.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
