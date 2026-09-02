from __future__ import annotations

import argparse
from pathlib import Path

from src.domain.core_skill_semantics import normalize_compiled_core_fields
from src.evaluation.models import EvaluationManifest, PredictionFile


def replay_core_normalization(
    manifest: EvaluationManifest,
    predictions: PredictionFile,
    *,
    prompt_version: str,
) -> PredictionFile:
    """Apply only current deterministic Core normalization to saved outputs."""

    source_by_id = {
        case.id: case.input.raw_content
        for case in manifest.cases
        if case.input.raw_content is not None
    }
    replayed = []
    for prediction in predictions.predictions:
        source_content = source_by_id.get(prediction.case_id)
        if prediction.fields is None or source_content is None:
            replayed.append(prediction)
            continue
        fields = normalize_compiled_core_fields(
            prediction.fields,
            source_content=source_content,
        )
        replayed.append(prediction.model_copy(update={"fields": fields}))

    return predictions.model_copy(
        update={
            "prompt_version": prompt_version,
            "generator_version": "evaluation-core-normalization-replay-v1",
            "generation_duration_ms": 0.0,
            "predictions": replayed,
        }
    )


def main() -> int:
    arguments = _parse_args()
    manifest = EvaluationManifest.model_validate_json(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    predictions = PredictionFile.model_validate_json(
        Path(arguments.predictions).read_text(encoding="utf-8")
    )
    replayed = replay_core_normalization(
        manifest,
        predictions,
        prompt_version=arguments.prompt_version,
    )
    output_path = Path(arguments.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        replayed.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"replayed cases={len(replayed.predictions)} "
        f"output={output_path}"
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay deterministic Core normalization on saved predictions"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prompt-version", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
