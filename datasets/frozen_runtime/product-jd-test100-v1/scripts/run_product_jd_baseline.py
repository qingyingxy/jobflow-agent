from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.domain.job import RawJobDocument
from src.evaluation.product_metrics import evaluate_product_dataset
from src.infrastructure.llm_client import (
    ModelClientError,
    StructuredModelClient,
    StructuredModelRequest,
    StructuredModelResponse,
    create_structured_model_client,
)
from src.services.jd_parser import JDParserError
from src.services.product_jd_parser import ProductJDParser

DEFAULT_DATASET = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v2-2026-09-06.json"
)
DEFAULT_PREDICTIONS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-two-stage-predictions-v5.json"
)
DEFAULT_REPORT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-two-stage-report-v5.json"
)
DEFAULT_PREDICTION_VERSION = "product-jd-development70-two-stage-v6"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _filter_dataset(
    dataset: dict[str, Any],
    case_ids: list[str],
) -> dict[str, Any]:
    if not case_ids:
        return dataset
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("--case-id values must be unique")
    cases_by_id = {case["id"]: case for case in dataset["cases"]}
    unknown = [case_id for case_id in case_ids if case_id not in cases_by_id]
    if unknown:
        raise ValueError(f"Unknown --case-id values: {unknown!r}")
    return {
        **dataset,
        "case_count": len(case_ids),
        "cases": [cases_by_id[case_id] for case_id in case_ids],
    }


class _ModelCallBudgetExhausted(ModelClientError):
    code = "model_call_budget_exhausted"


class _BudgetedModelClient:
    def __init__(
        self,
        client: StructuredModelClient,
        reserve_call: Callable[[], Awaitable[bool]],
    ) -> None:
        self._client = client
        self._reserve_call = reserve_call

    @property
    def model_name(self) -> str:
        return self._client.model_name

    @property
    def provider(self) -> str:
        return self._client.provider

    async def generate(
        self,
        request: StructuredModelRequest,
    ) -> StructuredModelResponse:
        if not await self._reserve_call():
            raise _ModelCallBudgetExhausted("已达到本轮模型调用上限")
        return await self._client.generate(request)


async def generate_predictions(
    dataset: dict[str, Any],
    *,
    predictions_path: Path,
    max_new_cases: int | None,
    max_model_calls: int | None,
    concurrency: int,
    validation_retries: int,
    resume: bool,
    retry_failures: bool = False,
    prediction_version: str = DEFAULT_PREDICTION_VERSION,
) -> dict[str, Any]:
    if concurrency < 1 or concurrency > 4:
        raise ValueError("concurrency must be between 1 and 4")
    if validation_retries not in {0, 1}:
        raise ValueError("validation_retries must be 0 or 1")
    if retry_failures and not resume:
        raise ValueError("retry_failures requires resume=True")
    settings = get_settings()
    base_client = create_structured_model_client(settings)
    reasoning_effort = (
        getattr(base_client, "reasoning_effort", None) or "provider_default"
    )
    response_format = getattr(base_client, "response_format", "provider_default")
    existing: dict[str, dict[str, Any]] = {}
    generated_at = datetime.now(UTC).isoformat()
    model_calls = 0
    lock = asyncio.Lock()

    async def reserve_call() -> bool:
        nonlocal model_calls
        async with lock:
            if max_model_calls is not None and model_calls >= max_model_calls:
                return False
            model_calls += 1
            return True

    client = _BudgetedModelClient(base_client, reserve_call)
    parser = ProductJDParser(client, validation_retries=validation_retries)
    if resume:
        if not predictions_path.exists():
            raise ValueError("--resume requires an existing predictions file")
        prior = json.loads(predictions_path.read_text(encoding="utf-8"))
        if prior["dataset_version"] != dataset["dataset_version"]:
            raise ValueError("Prediction checkpoint dataset version mismatch")
        if prior["model"] != base_client.model_name:
            raise ValueError("Prediction checkpoint model mismatch")
        if prior["schema_version"] != parser.schema_version:
            raise ValueError("Prediction checkpoint schema version mismatch")
        if prior["parser_version"] != parser.parser_version:
            raise ValueError("Prediction checkpoint parser version mismatch")
        if prior["prompt_version"] != parser.prompt_version:
            raise ValueError("Prediction checkpoint prompt version mismatch")
        if prior.get("reasoning_effort", "provider_default") != reasoning_effort:
            raise ValueError("Prediction checkpoint reasoning effort mismatch")
        prior_response_format = prior.get("response_format")
        if (
            prior_response_format is not None
            and prior_response_format != response_format
        ):
            raise ValueError("Prediction checkpoint response format mismatch")
        if prior.get("extraction_prompt_version") != parser.extraction_prompt_version:
            raise ValueError("Prediction checkpoint extraction prompt version mismatch")
        if prior.get("relation_prompt_version") != parser.relation_prompt_version:
            raise ValueError("Prediction checkpoint relation prompt version mismatch")
        existing = {item["case_id"]: item for item in prior["predictions"]}
        generated_at = prior["generated_at"]
        model_calls = sum(item.get("model_call_count", 0) for item in existing.values())

    retry_case_ids = (
        {
            case_id
            for case_id, prediction in existing.items()
            if prediction.get("output") is None
        }
        if retry_failures
        else set()
    )
    pending = [
        case
        for case in dataset["cases"]
        if case["id"] not in existing or case["id"] in retry_case_ids
    ]
    if max_new_cases is not None:
        pending = pending[:max_new_cases]
    semaphore = asyncio.Semaphore(concurrency)

    async def run_case(case: dict[str, Any]) -> dict[str, Any] | None:
        async with semaphore:
            started = perf_counter()
            document = RawJobDocument(
                source_url=case["source"]["source_url"],
                source_type="product_evaluation",
                raw_content=case["raw_content"],
                source_metadata={
                    "company": case["source"]["company"],
                    "title": case["source"]["title"],
                },
            )
            try:
                result = await parser.parse_model_output(document)
            except JDParserError as error:
                if error.code == _ModelCallBudgetExhausted.code:
                    return None
                return {
                    "case_id": case["id"],
                    "output": None,
                    "failure_code": error.code,
                    "model_call_count": int(
                        error.details.get("model_call_count") or 0
                    ),
                    "diagnostics": {
                        "message": str(error),
                        **error.details,
                        "duration_ms": round(
                            (perf_counter() - started) * 1000,
                            2,
                        ),
                    },
                }
            return {
                "case_id": case["id"],
                "output": result.output.model_dump(mode="json"),
                "raw_extraction": result.raw_extraction,
                "raw_relation_judgment": result.raw_relation_judgment,
                "failure_code": None,
                "model_call_count": result.model_call_count,
                "diagnostics": {
                    "stages": list(result.stage_diagnostics),
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            }

    def prediction_file() -> dict[str, Any]:
        order = {case["id"]: index for index, case in enumerate(dataset["cases"])}
        return {
            "prediction_version": prediction_version,
            "dataset_version": dataset["dataset_version"],
            "schema_version": parser.schema_version,
            "parser_version": parser.parser_version,
            "prompt_version": parser.prompt_version,
            "extraction_prompt_version": parser.extraction_prompt_version,
            "relation_prompt_version": parser.relation_prompt_version,
            "model": base_client.model_name,
            "reasoning_effort": reasoning_effort,
            "response_format": response_format,
            "generated_at": generated_at,
            "predictions": sorted(
                existing.values(),
                key=lambda item: order[item["case_id"]],
            ),
        }

    tasks = [asyncio.create_task(run_case(case)) for case in pending]
    for task in asyncio.as_completed(tasks):
        prediction = await task
        if prediction is None:
            continue
        previous = existing.get(prediction["case_id"])
        if previous is not None and previous.get("output") is None:
            diagnostics = dict(prediction.get("diagnostics") or {})
            diagnostics["previous_attempt"] = {
                "failure_code": previous.get("failure_code"),
                "model_call_count": previous.get("model_call_count", 0),
                "diagnostics": previous.get("diagnostics"),
            }
            prediction["diagnostics"] = diagnostics
            prediction["model_call_count"] = prediction.get(
                "model_call_count", 0
            ) + previous.get("model_call_count", 0)
        existing[prediction["case_id"]] = prediction
        _write_json(predictions_path, prediction_file())
    result = prediction_file()
    _write_json(predictions_path, result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Product JD evaluation")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--prediction-version",
        default=DEFAULT_PREDICTION_VERSION,
    )
    parser.add_argument("--max-new-cases", type=int)
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--validation-retries", type=int, choices=(0, 1), default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument(
        "--case-id",
        dest="case_ids",
        action="append",
        default=[],
        help="Run or evaluate only this dataset case; may be repeated",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    dataset = _filter_dataset(
        json.loads(args.dataset.read_text(encoding="utf-8")),
        args.case_ids,
    )
    if args.evaluate_only:
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    else:
        predictions = asyncio.run(
            generate_predictions(
                dataset,
                predictions_path=args.predictions,
                max_new_cases=args.max_new_cases,
                max_model_calls=args.max_model_calls,
                concurrency=args.concurrency,
                validation_retries=args.validation_retries,
                resume=args.resume,
                retry_failures=args.retry_failures,
                prediction_version=args.prediction_version,
            )
        )
    report = evaluate_product_dataset(dataset, predictions)
    report["prediction_version"] = predictions["prediction_version"]
    report["model"] = predictions["model"]
    _write_json(args.report, report)
    print(
        "product-jd-evaluation "
        f"cases={report['case_count']} "
        f"predictions={report['prediction_count']} "
        f"attempted_parse_success={report['attempted_parse_success_rate']:.4f} "
        f"facts_value_f1={report['facts']['value_macro_f1']:.4f} "
        "facts_source_f1="
        f"{report['facts']['source_character_macro_f1']:.4f} "
        "requirements_character_f1="
        f"{report['requirements']['character_coverage']['all']['f1']:.4f} "
        "any_of_relation_f1="
        f"{report['requirements']['any_of']['aligned_relation_groups']['f1']:.4f} "
        "any_of_aligned_exact_f1="
        f"{report['requirements']['any_of']['aligned_exact_item_groups']['f1']:.4f} "
        "any_of_source_f1="
        f"{report['requirements']['any_of']['source_character_coverage']['f1']:.4f} "
        "responsibilities_character_f1="
        f"{report['responsibilities']['character_coverage']['f1']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
