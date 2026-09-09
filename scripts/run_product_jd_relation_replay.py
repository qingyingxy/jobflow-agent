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

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.domain.job import RawJobDocument
from src.domain.product_jd import (
    ProductJDExtractionOutput,
    ProductJDModelOutput,
    ProductRelationJudgmentOutput,
    ProductRequirement,
    validate_product_jd_extraction,
    validate_product_jd_output,
    validate_product_relation_judgment,
)
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
    / "product-jd-development70-v3-human-reviewed-2026-09-07.json"
)
DEFAULT_SOURCE_PREDICTIONS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-terra-medium-json-object-v4-predictions-v1.json"
)
DEFAULT_PREDICTIONS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v4-extraction-relation-v5-replay-predictions-v1.json"
)
DEFAULT_REPORT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v4-extraction-relation-v5-replay-report-v1.json"
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
            raise _ModelCallBudgetExhausted("relation replay model-call budget exhausted")
        return await self._client.generate(request)


def _build_output(
    extraction: ProductJDExtractionOutput,
    judgment: ProductRelationJudgmentOutput | None,
) -> ProductJDModelOutput:
    if judgment is None:
        requirements: list[ProductRequirement] = []
    else:
        decisions = {
            decision.requirement_index: decision for decision in judgment.decisions
        }
        requirements = [
            ProductRequirement(
                source_text=requirement.source_text,
                level=requirement.level,
                relation=decisions[index].relation,
                items=decisions[index].items,
                relation_reason=decisions[index].reason,
            )
            for index, requirement in enumerate(extraction.requirements)
        ]
    return ProductJDModelOutput(
        facts=extraction.facts,
        requirements=requirements,
        responsibilities=extraction.responsibilities,
    )


async def generate_relation_replay(
    dataset: dict[str, Any],
    source_prediction_file: dict[str, Any],
    *,
    predictions_path: Path,
    max_model_calls: int | None,
    concurrency: int,
    validation_retries: int,
    resume: bool,
) -> dict[str, Any]:
    if concurrency < 1 or concurrency > 4:
        raise ValueError("concurrency must be between 1 and 4")
    if validation_retries not in {0, 1}:
        raise ValueError("validation_retries must be 0 or 1")

    settings = get_settings()
    base_client = create_structured_model_client(settings)
    reasoning_effort = (
        getattr(base_client, "reasoning_effort", None) or "provider_default"
    )
    response_format = getattr(base_client, "response_format", "provider_default")
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
    source_predictions = {
        item["case_id"]: item for item in source_prediction_file["predictions"]
    }
    dataset_ids = [case["id"] for case in dataset["cases"]]
    missing_source = [case_id for case_id in dataset_ids if case_id not in source_predictions]
    if missing_source:
        raise ValueError(f"Source predictions are missing cases: {missing_source!r}")

    existing: dict[str, dict[str, Any]] = {}
    if resume:
        if not predictions_path.exists():
            raise ValueError("--resume requires an existing predictions file")
        prior = json.loads(predictions_path.read_text(encoding="utf-8"))
        expected = {
            "dataset_version": dataset["dataset_version"],
            "source_prediction_version": source_prediction_file["prediction_version"],
            "relation_prompt_version": parser.relation_prompt_version,
            "model": base_client.model_name,
            "reasoning_effort": reasoning_effort,
            "response_format": response_format,
        }
        for field, value in expected.items():
            if prior.get(field) != value:
                raise ValueError(f"Relation replay checkpoint {field} mismatch")
        existing = {item["case_id"]: item for item in prior["predictions"]}
        generated_at = prior["generated_at"]
        model_calls = sum(item.get("model_call_count", 0) for item in existing.values())

    pending = [case for case in dataset["cases"] if case["id"] not in existing]
    semaphore = asyncio.Semaphore(concurrency)

    async def run_case(case: dict[str, Any]) -> dict[str, Any] | None:
        async with semaphore:
            started = perf_counter()
            source_prediction = source_predictions[case["id"]]
            raw_extraction = source_prediction.get("raw_extraction")
            if not isinstance(raw_extraction, dict):
                return {
                    "case_id": case["id"],
                    "output": None,
                    "failure_code": "source_extraction_missing",
                    "model_call_count": 0,
                    "diagnostics": {"duration_ms": 0.0},
                }
            try:
                extraction = ProductJDExtractionOutput.model_validate(raw_extraction)
                validate_product_jd_extraction(extraction, case["raw_content"])
            except (TypeError, ValueError, ValidationError) as error:
                return {
                    "case_id": case["id"],
                    "output": None,
                    "failure_code": "source_extraction_invalid",
                    "model_call_count": 0,
                    "diagnostics": {
                        "message": str(error),
                        "duration_ms": round((perf_counter() - started) * 1000, 2),
                    },
                }

            document = RawJobDocument(
                source_url=case["source"]["source_url"],
                source_type="product_relation_replay",
                raw_content=case["raw_content"],
                source_metadata={
                    "company": case["source"]["company"],
                    "title": case["source"]["title"],
                },
            )
            judgment: ProductRelationJudgmentOutput | None = None
            raw_relation_judgment: dict[str, Any] | None = None
            response: StructuredModelResponse | None = None
            case_model_calls = 0
            if extraction.requirements:

                def validate_relations(
                    raw_output: dict[str, Any],
                ) -> ProductRelationJudgmentOutput:
                    value = ProductRelationJudgmentOutput.model_validate(raw_output)
                    validate_product_relation_judgment(value, extraction)
                    return value

                try:
                    stage = await parser._run_stage(
                        parser.build_relation_request(document, extraction),
                        stage="relation_replay",
                        validator=validate_relations,
                    )
                except JDParserError as error:
                    if getattr(error, "code", None) == _ModelCallBudgetExhausted.code:
                        return None
                    case_model_calls = int(
                        getattr(error, "details", {}).get("model_call_count") or 0
                    )
                    return {
                        "case_id": case["id"],
                        "output": None,
                        "failure_code": getattr(error, "code", "relation_replay_failed"),
                        "model_call_count": case_model_calls,
                        "diagnostics": {
                            "message": str(error),
                            "duration_ms": round(
                                (perf_counter() - started) * 1000,
                                2,
                            ),
                        },
                    }
                judgment = stage.value
                response = stage.response
                case_model_calls = stage.model_call_count
                raw_relation_judgment = response.output

            output = _build_output(extraction, judgment)
            validate_product_jd_output(output, case["raw_content"])
            diagnostics: dict[str, Any] = {
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "source_extraction_reused": True,
            }
            if response is not None:
                diagnostics.update(
                    {
                        "response_id": response.response_id,
                        "finish_reason": response.finish_reason,
                        "usage": response.usage,
                        "request_duration_ms": response.request_duration_ms,
                    }
                )
            return {
                "case_id": case["id"],
                "output": output.model_dump(mode="json"),
                "raw_extraction": raw_extraction,
                "raw_relation_judgment": raw_relation_judgment,
                "failure_code": None,
                "model_call_count": case_model_calls,
                "diagnostics": diagnostics,
            }

    def prediction_file() -> dict[str, Any]:
        order = {case_id: index for index, case_id in enumerate(dataset_ids)}
        return {
            "prediction_version": "product-jd-relation-replay-v1",
            "dataset_version": dataset["dataset_version"],
            "schema_version": parser.schema_version,
            "parser_version": parser.parser_version,
            "prompt_version": parser.prompt_version,
            "extraction_prompt_version": source_prediction_file.get(
                "extraction_prompt_version"
            ),
            "relation_prompt_version": parser.relation_prompt_version,
            "source_prediction_version": source_prediction_file["prediction_version"],
            "source_dataset_version": source_prediction_file["dataset_version"],
            "model": base_client.model_name,
            "reasoning_effort": reasoning_effort,
            "response_format": response_format,
            "generated_at": generated_at,
            "replay_mode": "reuse_source_raw_extraction_relation_only",
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
        existing[prediction["case_id"]] = prediction
        _write_json(predictions_path, prediction_file())
    result = prediction_file()
    _write_json(predictions_path, result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay only Product JD relation judgment on saved extraction"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--source-predictions",
        type=Path,
        default=DEFAULT_SOURCE_PREDICTIONS,
    )
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--validation-retries", type=int, choices=(0, 1), default=1)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    source_predictions = json.loads(
        args.source_predictions.read_text(encoding="utf-8")
    )
    predictions = asyncio.run(
        generate_relation_replay(
            dataset,
            source_predictions,
            predictions_path=args.predictions,
            max_model_calls=args.max_model_calls,
            concurrency=args.concurrency,
            validation_retries=args.validation_retries,
            resume=args.resume,
        )
    )
    report = evaluate_product_dataset(dataset, predictions)
    report["prediction_version"] = predictions["prediction_version"]
    report["source_prediction_version"] = predictions["source_prediction_version"]
    report["model"] = predictions["model"]
    _write_json(args.report, report)
    print(
        "product-jd-relation-replay "
        f"cases={report['case_count']} "
        f"predictions={report['prediction_count']} "
        f"attempted_parse_success={report['attempted_parse_success_rate']:.4f} "
        "requirements_character_f1="
        f"{report['requirements']['character_coverage']['all']['f1']:.4f} "
        "any_of_relation_f1="
        f"{report['requirements']['any_of']['aligned_relation_groups']['f1']:.4f} "
        "any_of_aligned_f1="
        f"{report['requirements']['any_of']['aligned_exact_item_groups']['f1']:.4f} "
        "any_of_source_f1="
        f"{report['requirements']['any_of']['source_character_coverage']['f1']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
