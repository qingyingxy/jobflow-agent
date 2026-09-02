from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from src.evaluation.models import EvaluationManifest, PredictionFile, PredictionRecord


def merge_predictions(
    manifest: EvaluationManifest,
    prediction_files: list[PredictionFile],
    *,
    prediction_version: str,
) -> PredictionFile:
    """Merge prediction shards in manifest order and reject gaps or duplicates."""

    predictions_by_id: dict[str, PredictionRecord] = {}
    for prediction_file in prediction_files:
        for prediction in prediction_file.predictions:
            if prediction.case_id in predictions_by_id:
                raise ValueError(f"duplicate prediction: {prediction.case_id}")
            predictions_by_id[prediction.case_id] = prediction

    expected_ids = [case.id for case in manifest.cases if case.split == manifest.split]
    missing_ids = [case_id for case_id in expected_ids if case_id not in predictions_by_id]
    extra_ids = sorted(set(predictions_by_id) - set(expected_ids))
    if missing_ids or extra_ids:
        raise ValueError(f"prediction coverage mismatch: missing={missing_ids}, extra={extra_ids}")

    models = {item.model for item in prediction_files}
    prompt_versions = {item.prompt_version for item in prediction_files}
    if len(models) != 1 or len(prompt_versions) != 1:
        raise ValueError(
            "prediction shards must use one model and prompt version: "
            f"models={sorted(str(item) for item in models)}, "
            f"prompts={sorted(str(item) for item in prompt_versions)}"
        )

    ordered = [predictions_by_id[case_id] for case_id in expected_ids]
    return PredictionFile(
        prediction_version=prediction_version,
        predictions=ordered,
        model=next(iter(models)),
        prompt_version=next(iter(prompt_versions)),
        generator_version="evaluation-prediction-merge-v1",
        generated_at=datetime.now(UTC).isoformat(),
        generation_duration_ms=sum(
            item.generation_duration_ms or 0.0 for item in prediction_files
        ),
        prediction_failure_count=sum(
            prediction.failure_code is not None for prediction in ordered
        ),
    )


def main() -> int:
    arguments = _parse_args()
    manifest = EvaluationManifest.model_validate_json(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    prediction_files = [
        PredictionFile.model_validate_json(Path(path).read_text(encoding="utf-8"))
        for path in arguments.predictions
    ]
    merged = merge_predictions(
        manifest,
        prediction_files,
        prediction_version=arguments.prediction_version,
    )
    output_path = Path(arguments.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(merged.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        f"merged cases={len(merged.predictions)} "
        f"failures={merged.prediction_failure_count} output={output_path}"
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge prediction shards in evaluation manifest order"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--predictions", required=True, nargs="+")
    parser.add_argument("--output", required=True)
    parser.add_argument("--prediction-version", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
