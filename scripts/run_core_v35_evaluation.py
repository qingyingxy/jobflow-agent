from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

CANARY_MANIFEST = Path(
    "artifacts/evaluation/m11-core-v35-synthetic-canary-v1-2026-09-03.json"
)
CANARY_OUTPUT = Path(
    "artifacts/evaluation/"
    "m11-core-v35-synthetic-canary-predictions-v1-api-2026-09-03.json"
)
CANARY_CHECKPOINT = Path(
    "artifacts/evaluation/"
    "m11-core-v35-synthetic-canary-predictions-v1-api-2026-09-03.checkpoint.json"
)
COMPARISON_MANIFEST = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v35-dev4-comparison-v1-2026-09-03.json"
)
COMPARISON_OUTPUT = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-predictions-core-v35-dev4-comparison-v1-api-2026-09-03.json"
)
COMPARISON_CHECKPOINT = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-predictions-core-v35-dev4-comparison-v1-api-2026-09-03.checkpoint.json"
)

RUN_ENVIRONMENT = {
    "STRUCTURED_MODEL_PROVIDER": "openai_compatible",
    "LLM_MODEL": "deepseek-v4-flash",
    "LLM_RESPONSE_FORMAT": "json_object",
    "LLM_THINKING_MODE": "disabled",
    "LLM_REASONING_EFFORT": "auto",
    "LLM_TIMEOUT_SECONDS": "60",
    "LLM_MAX_RETRIES": "0",
    "PARSER_VALIDATION_RETRIES": "0",
    "CORE_PROMPT_VERSION": "jd-core-parser-prompt-v23",
    "CORE_PARSER_VERSION": "jd-core-parser-v35",
}


def _configure_environment() -> None:
    os.environ.update(RUN_ENVIRONMENT)


def _client_summary() -> dict[str, Any]:
    from src.config import Settings
    from src.infrastructure.llm_client import create_structured_model_client

    settings = Settings()
    client = create_structured_model_client(settings)
    summary = {
        "provider": settings.structured_model_provider,
        "model": settings.llm_model,
        "response_format": getattr(client, "_response_format", None),
        "thinking_mode": getattr(client, "_thinking_mode", None),
        "timeout_seconds": getattr(client, "_timeout_seconds", None),
        "model_retries": getattr(client, "_max_retries", None),
        "parser_retries": settings.parser_validation_retries,
        "parser_version": settings.core_parser_version,
        "prompt_version": settings.core_prompt_version,
    }
    expected = {
        "provider": "openai_compatible",
        "model": "deepseek-v4-flash",
        "response_format": "json_object",
        "thinking_mode": "disabled",
        "timeout_seconds": 60.0,
        "model_retries": 0,
        "parser_retries": 0,
        "parser_version": "jd-core-parser-v35",
        "prompt_version": "jd-core-parser-prompt-v23",
    }
    if summary != expected:
        raise SystemExit(f"v35 runtime configuration mismatch: {summary}")
    return summary


def _require_canary_success() -> None:
    if not CANARY_OUTPUT.exists():
        raise SystemExit("v35 canary output is missing")
    payload = json.loads(CANARY_OUTPUT.read_text(encoding="utf-8"))
    predictions = payload.get("predictions") or []
    if (
        len(predictions) != 1
        or predictions[0].get("failure_code") is not None
        or payload.get("prediction_failure_count") != 0
    ):
        raise SystemExit("v35 canary did not succeed; refusing four-case comparison")


def _run(manifest: Path, output: Path, checkpoint: Path) -> int:
    if output.exists() or checkpoint.exists():
        raise SystemExit(
            "refusing to repeat a v35 API run because its output or checkpoint exists"
        )
    from src.evaluation.predict import main as predict_main

    sys.argv = [
        "python -m src.evaluation.predict",
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--checkpoint",
        str(checkpoint),
        "--parser-only",
        "--parser-mode",
        "core",
        "--concurrency",
        "1",
        "--case-timeout",
        "90",
    ]
    return predict_main()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=("preflight", "canary", "comparison"))
    arguments = parser.parse_args()

    _configure_environment()
    summary = _client_summary()
    if arguments.target == "preflight":
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    if arguments.target == "canary":
        return _run(CANARY_MANIFEST, CANARY_OUTPUT, CANARY_CHECKPOINT)
    _require_canary_success()
    return _run(COMPARISON_MANIFEST, COMPARISON_OUTPUT, COMPARISON_CHECKPOINT)


if __name__ == "__main__":
    raise SystemExit(main())
