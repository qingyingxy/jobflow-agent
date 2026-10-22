from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from src.config import get_settings
from src.evaluation.model_first import (
    ModelFirstCanonicalFile,
    build_canonical_projection_file,
)
from src.evaluation.predict_unified import generate_unified_predictions
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
)
from src.infrastructure.llm_client import (
    ModelClientError,
    StructuredModelClient,
    create_structured_model_client,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT / "artifacts/evaluation/unified-jd-model-first-v1-dev20-2026-09-05.json"
)
DEFAULT_PREDICTIONS = (
    ROOT
    / "artifacts/evaluation/unified-jd-model-first-v1-dev20-predictions-v1-2026-09-05.json"
)
DEFAULT_CANONICAL = (
    ROOT
    / "artifacts/evaluation/unified-jd-model-first-v1-dev20-canonical-v1-2026-09-05.json"
)
DEFAULT_CHECKPOINT = DEFAULT_PREDICTIONS.with_suffix(".checkpoint.json")
MAX_MODEL_CALLS = 21


async def generate_model_first_artifacts(
    manifest: UnifiedEvaluationManifest,
    *,
    client: StructuredModelClient,
    checkpoint_path: Path | None = None,
    resume: bool = False,
    concurrency: int = 1,
    max_new_cases: int | None = None,
    stop_on_failure: bool = False,
) -> tuple[UnifiedPredictionFile, ModelFirstCanonicalFile]:
    predictions = await generate_unified_predictions(
        manifest,
        client=client,
        concurrency=concurrency,
        checkpoint_path=checkpoint_path,
        resume=resume,
        max_new_cases=max_new_cases,
        max_model_calls=MAX_MODEL_CALLS,
        stop_on_failure=stop_on_failure,
        parser_mode="model_first_v1",
        validation_retries=1,
    )
    canonical = build_canonical_projection_file(manifest, predictions)
    return predictions, canonical


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full-JD model-first v1 development baseline"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--concurrency", type=int, default=1, choices=(1, 2, 3, 4))
    parser.add_argument("--max-new-cases", type=int)
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--allow-fake", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    reserved_outputs = [arguments.predictions, arguments.canonical]
    existing = [str(path) for path in reserved_outputs if path.exists()]
    if existing:
        raise SystemExit(f"refusing to call the model before overwriting: {existing}")
    if arguments.resume:
        if not arguments.checkpoint.exists():
            raise SystemExit("--resume requires an existing checkpoint")
    elif arguments.checkpoint.exists():
        raise SystemExit("checkpoint already exists; use --resume or a new output path")

    manifest = UnifiedEvaluationManifest.model_validate_json(
        arguments.manifest.read_text(encoding="utf-8")
    )
    settings = get_settings()
    if settings.structured_model_provider.strip().lower() == "fake" and not (
        arguments.allow_fake
    ):
        raise SystemExit(
            "model-first baseline requires a real structured model provider"
        )
    one_transport_attempt = settings.model_copy(update={"llm_max_retries": 0})
    try:
        client = create_structured_model_client(one_transport_attempt)
    except ModelClientError as error:
        raise SystemExit(f"cannot create structured model client: {error}") from error

    predictions, canonical = asyncio.run(
        generate_model_first_artifacts(
            manifest,
            client=client,
            checkpoint_path=arguments.checkpoint,
            resume=arguments.resume,
            concurrency=arguments.concurrency,
            max_new_cases=arguments.max_new_cases,
            stop_on_failure=arguments.stop_on_failure,
        )
    )
    calls = sum(item.model_call_count or 0 for item in predictions.predictions)
    repairs = sum(
        max(0, (item.model_call_count or 0) - 1) for item in predictions.predictions
    )
    failures = sum(item.failure_code is not None for item in predictions.predictions)
    completed_cases = len(predictions.predictions)
    total_cases = len(manifest.cases)
    if completed_cases < total_cases:
        print(
            "model-first baseline checkpointed "
            f"cases={completed_cases}/{total_cases} "
            f"calls={calls}/{MAX_MODEL_CALLS} repairs={repairs} "
            f"failures={failures} model={client.model_name}"
        )
        print(f"checkpoint={arguments.checkpoint}")
        return 3

    _write_new(arguments.predictions, predictions.model_dump_json(indent=2) + "\n")
    _write_new(arguments.canonical, canonical.model_dump_json(indent=2) + "\n")
    print(
        "model-first baseline complete "
        f"cases={completed_cases}/{total_cases} "
        f"calls={calls}/{MAX_MODEL_CALLS} repairs={repairs} "
        f"failures={failures} model={client.model_name}"
    )
    print(f"predictions={arguments.predictions}")
    print(f"canonical={arguments.canonical}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
