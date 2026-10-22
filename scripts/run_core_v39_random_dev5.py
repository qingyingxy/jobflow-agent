from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

MANIFEST = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v39-random-dev5-v1-2026-09-03.json"
)
OUTPUT = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-predictions-core-v39-random-dev5-v1-api-2026-09-03.json"
)
CHECKPOINT = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-predictions-core-v39-random-dev5-v1-api-2026-09-03.checkpoint.json"
)

RUN_ENVIRONMENT = {
    "STRUCTURED_MODEL_PROVIDER": "openai_compatible",
    "LLM_MODEL": "deepseek-v4-flash",
    "LLM_RESPONSE_FORMAT": "json_object",
    "LLM_THINKING_MODE": "disabled",
    "LLM_TIMEOUT_SECONDS": "60",
    "LLM_MAX_RETRIES": "0",
    "PARSER_VALIDATION_RETRIES": "0",
    "CORE_PROMPT_VERSION": "jd-core-parser-prompt-v24",
    "CORE_PARSER_VERSION": "jd-core-parser-v39",
}


def _configure_environment() -> None:
    os.environ.update(RUN_ENVIRONMENT)


def _client_summary() -> dict[str, Any]:
    from src.config import Settings
    from src.domain.skill_normalizer import SKILL_ONTOLOGY_VERSION
    from src.infrastructure.llm_client import create_structured_model_client
    from src.services.core_jd_parser import CORE_MAX_OUTPUT_TOKENS, CORE_SCHEMA_VERSION

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
        "schema_version": CORE_SCHEMA_VERSION,
        "skill_ontology_version": SKILL_ONTOLOGY_VERSION,
        "max_tokens": CORE_MAX_OUTPUT_TOKENS,
        "concurrency": 1,
        "case_timeout_seconds": 90,
    }
    expected = {
        "provider": "openai_compatible",
        "model": "deepseek-v4-flash",
        "response_format": "json_object",
        "thinking_mode": "disabled",
        "timeout_seconds": 60.0,
        "model_retries": 0,
        "parser_retries": 0,
        "parser_version": "jd-core-parser-v39",
        "prompt_version": "jd-core-parser-prompt-v24",
        "schema_version": "core-job-fields-v10",
        "skill_ontology_version": "skill-ontology-v5",
        "max_tokens": 4096,
        "concurrency": 1,
        "case_timeout_seconds": 90,
    }
    if summary != expected:
        raise SystemExit(f"v39 random-dev5 configuration mismatch: {summary}")
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
            "refusing to repeat the v39 random-dev5 API run because output or "
            "checkpoint exists"
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
