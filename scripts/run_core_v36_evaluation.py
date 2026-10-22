from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

MANIFEST = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v36-dev4-comparison-v1-2026-09-03.json"
)
OUTPUT = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-predictions-core-v36-dev4-comparison-v1-api-2026-09-03.json"
)
CHECKPOINT = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-predictions-core-v36-dev4-comparison-v1-api-2026-09-03.checkpoint.json"
)

RUN_ENVIRONMENT = {
    "LLM_THINKING_MODE": "disabled",
    "LLM_TIMEOUT_SECONDS": "60",
    "LLM_MAX_RETRIES": "0",
    "PARSER_VALIDATION_RETRIES": "0",
    "CORE_PROMPT_VERSION": "jd-core-parser-prompt-v23",
    "CORE_PARSER_VERSION": "jd-core-parser-v36",
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
        "parser_version": "jd-core-parser-v36",
        "prompt_version": "jd-core-parser-prompt-v23",
    }
    if summary != expected:
        raise SystemExit(f"v36 runtime configuration mismatch: {summary}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=("preflight", "comparison"))
    arguments = parser.parse_args()

    _configure_environment()
    summary = _client_summary()
    if arguments.target == "preflight":
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    if OUTPUT.exists() or CHECKPOINT.exists():
        raise SystemExit(
            "refusing to repeat the v36 API run because output or checkpoint exists"
        )

    from src.evaluation.predict import main as predict_main

    sys.argv = [
        "python -m src.evaluation.predict",
        "--manifest",
        str(MANIFEST),
        "--output",
        str(OUTPUT),
        "--checkpoint",
        str(CHECKPOINT),
        "--parser-only",
        "--parser-mode",
        "core",
        "--concurrency",
        "1",
        "--case-timeout",
        "90",
    ]
    return predict_main()


if __name__ == "__main__":
    raise SystemExit(main())
