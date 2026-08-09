from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.evaluation.agent_runs import summarize_agent_runs
from src.evaluation.metrics import evaluate_manifest
from src.evaluation.models import EvaluationManifest, PredictionFile


def main() -> int:
    started_at = datetime.now(UTC)
    started_clock = perf_counter()
    arguments = _parse_args()
    manifest = _load_manifest(Path(arguments.manifest))
    prediction_file = _load_predictions(Path(arguments.predictions))
    evaluation_manifest = manifest
    evaluation_predictions = prediction_file.predictions
    evaluation_scope = {
        "mode": "all_predictions",
        "source_case_count": len(
            [case for case in manifest.cases if case.split == manifest.split]
        ),
        "excluded_failure_count": 0,
    }
    if arguments.successful_only:
        successful_ids = {
            prediction.case_id
            for prediction in prediction_file.predictions
            if prediction.failure_code is None
        }
        evaluation_cases = [
            case
            for case in manifest.cases
            if case.split == manifest.split and case.id in successful_ids
        ]
        if not evaluation_cases:
            raise SystemExit("--successful-only 没有可评测的成功预测")
        evaluation_manifest = manifest.model_copy(update={"cases": evaluation_cases})
        evaluation_predictions = [
            prediction
            for prediction in prediction_file.predictions
            if prediction.failure_code is None and prediction.case_id in successful_ids
        ]
        evaluation_scope = {
            "mode": "successful_predictions_only",
            "source_case_count": len(
                [case for case in manifest.cases if case.split == manifest.split]
            ),
            "evaluated_case_count": len(evaluation_cases),
            "excluded_failure_count": 0,
        }
        evaluation_scope["excluded_failure_count"] = (
            evaluation_scope["source_case_count"]
            - evaluation_scope["evaluated_case_count"]
        )
    model = arguments.model or prediction_file.model
    prompt_version = arguments.prompt_version or prediction_file.prompt_version
    report = evaluate_manifest(
        evaluation_manifest,
        evaluation_predictions,
        model=model,
        prompt_version=prompt_version,
        validator_version=arguments.validator_version,
    )
    report["evaluation_scope"] = evaluation_scope
    report["prediction_version"] = prediction_file.prediction_version
    report["prediction_generation"] = {
        "model": prediction_file.model,
        "prompt_version": prediction_file.prompt_version,
        "generator_version": prediction_file.generator_version,
        "generated_at": prediction_file.generated_at,
        "generation_duration_ms": prediction_file.generation_duration_ms,
        "prediction_failure_count": prediction_file.prediction_failure_count,
    }
    report["run"] = _run_metadata(
        report,
        arguments=arguments,
        started_at=started_at,
        duration_ms=(perf_counter() - started_clock) * 1000,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"

    if arguments.output:
        output_path = Path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(
        "evaluation "
        f"dataset={report['dataset_version']} "
        f"split={report['split']} "
        f"cases={report['case_count']} "
        f"macro_f1={_display(report['validated']['macro_f1'])} "
        f"eligibility_accuracy={_display(report['validated']['eligibility_accuracy'])} "
        f"unsupported_claim_rate={_display(report['validated']['unsupported_claim_rate'])}"
    )
    if arguments.output:
        print(f"report={arguments.output}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic JobFlow evaluation")
    parser.add_argument("--manifest", required=True, help="Versioned evaluation manifest")
    parser.add_argument("--predictions", required=True, help="Model prediction JSON")
    parser.add_argument("--output", help="Optional machine-readable report path")
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--validator-version", default="evidence-boundary-v1")
    parser.add_argument(
        "--database-url",
        help="Optional SQLAlchemy URL used to summarize persisted AgentRun rows",
    )
    parser.add_argument("--user-id", help="Limit AgentRun summary to one user")
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Generation temperature recorded in run metadata",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Optional generation seed recorded in run metadata",
    )
    parser.add_argument(
        "--successful-only",
        action="store_true",
        help="只统计没有 failure_code 的成功预测，补充排除模型调用失败影响的指标",
    )
    return parser.parse_args()


def _load_manifest(path: Path) -> EvaluationManifest:
    return EvaluationManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _load_predictions(path: Path) -> PredictionFile:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return PredictionFile(prediction_version="unversioned", predictions=payload)
    return PredictionFile.model_validate(payload)


def _display(value: Any) -> str:
    return "undefined" if value is None else f"{value:.4f}"


def _run_metadata(
    report: dict[str, Any],
    *,
    arguments: argparse.Namespace,
    started_at: datetime,
    duration_ms: float,
) -> dict[str, Any]:
    agent_runs = None
    if arguments.database_url:
        agent_runs = _load_agent_run_summary(
            arguments.database_url,
            user_id=arguments.user_id,
        )
    prediction_records = report["prediction_count"]
    return {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_ms": round(duration_ms, 2),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "generation": {
            "temperature": arguments.temperature,
            "seed": arguments.seed,
        },
        "prediction_failure_count": report["prediction_failure_count"],
        "prediction_record_count": prediction_records,
        "agent_runs": agent_runs,
    }


def _load_agent_run_summary(
    database_url: str,
    *,
    user_id: str | None,
) -> dict[str, Any]:
    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        with factory() as session:
            return summarize_agent_runs(session, user_id=user_id)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
