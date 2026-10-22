from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from src.domain.skill_normalizer import SKILL_ONTOLOGY_VERSION
from src.evaluation.models import EvaluationManifest
from src.services.core_jd_parser import (
    CORE_MAX_OUTPUT_TOKENS,
    CORE_SCHEMA_VERSION,
    DEFAULT_CORE_PARSER_VERSION,
    DEFAULT_CORE_PROMPT_VERSION,
)

SOURCE_MANIFEST_PATH = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v37-random-dev5-v1-2026-09-03.json"
)
SELECTION_PATH = Path(
    "datasets/ai_campus_v37_random_dev5_selection_2026_09_03.json"
)
MANIFEST_PATH = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v38-random-dev5-v1-2026-09-03.json"
)
FREEZE_PATH = Path(
    "datasets/ai_campus_v38_random_dev5_execution_freeze_v1_2026_09_03.json"
)
FROZEN_AT = "2026-09-03T11:08:48+08:00"

PARSER_FILES = (
    Path("src/config.py"),
    Path("src/services/core_jd_parser.py"),
    Path("src/domain/core_skill_semantics.py"),
    Path("src/domain/skill_normalizer.py"),
    Path("src/domain/job.py"),
    Path("src/infrastructure/llm_client.py"),
    Path("scripts/run_core_v38_random_dev5.py"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"refusing to overwrite changed artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def build_manifest() -> dict[str, Any]:
    source = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload = copy.deepcopy(source)
    payload["manifest_version"] = "m11-ai-campus-v38-random-dev5-v1"
    payload["dataset_version"] = "m11-ai-v38-random-dev5-v1-2026-09-03"
    payload["purpose"] = (
        "Compare Parser v38 on the exact v37 random dev-5 sample after the "
        "generic singleton-any_of compatibility fix."
    )
    payload["source_policy"] = (
        "Reuse the exact reproducibly sampled five public dev JDs and labels. "
        "This is a development comparison, not an unseen evaluation."
    )
    for case in payload["cases"]:
        case["source"]["authorization"] = (
            "User requested a random current-dataset Parser test and evidence-"
            "based follow-up on 2026-09-03."
        )
        case["input"]["scenario"] = "v38_same_random_dev5_comparison"
        tags = case["expected"].setdefault("tags", [])
        if "v38_same_random_dev5" not in tags:
            tags.append("v38_same_random_dev5")
    return EvaluationManifest.model_validate(payload).model_dump(mode="json")


def main() -> None:
    actual_contract = (
        DEFAULT_CORE_PARSER_VERSION,
        DEFAULT_CORE_PROMPT_VERSION,
        CORE_SCHEMA_VERSION,
        SKILL_ONTOLOGY_VERSION,
        CORE_MAX_OUTPUT_TOKENS,
    )
    expected_contract = (
        "jd-core-parser-v38",
        "jd-core-parser-prompt-v23",
        "core-job-fields-v10",
        "skill-ontology-v4",
        4096,
    )
    if actual_contract != expected_contract:
        raise ValueError("runtime parser contract no longer matches Parser v38")

    write_json(MANIFEST_PATH, build_manifest())
    freeze = {
        "freeze_version": "ai-campus-v38-random-dev5-execution-freeze-v1",
        "frozen_at": FROZEN_AT,
        "purpose": "one Parser v38 same-random-dev5 comparison",
        "frozen_contract": {
            "parser": DEFAULT_CORE_PARSER_VERSION,
            "prompt": DEFAULT_CORE_PROMPT_VERSION,
            "schema": CORE_SCHEMA_VERSION,
            "skill_ontology": SKILL_ONTOLOGY_VERSION,
            "response_format": "json_object",
            "thinking_mode": "disabled",
            "max_tokens": CORE_MAX_OUTPUT_TOKENS,
            "files": {path.as_posix(): file_record(path) for path in PARSER_FILES},
        },
        "selection": file_record(SELECTION_PATH),
        "manifest": file_record(MANIFEST_PATH),
        "v37_result_basis": {
            "predictions": file_record(
                Path(
                    "artifacts/evaluation/"
                    "m11-ai-campus-predictions-core-v37-random-dev5-v1-api-"
                    "2026-09-03.json"
                )
            ),
            "valid_predictions": 4,
            "structured_output_invalid_cases": 1,
            "all_case_macro_f1": 0.6602046102046102,
        },
        "generic_change": (
            "downgrade singleton any_of clauses to ordinary single-skill all_of"
        ),
        "api_authorization": {
            "authorized_at": "2026-09-03",
            "destination": "configured DeepSeek API",
            "public_jd_count": 5,
            "run_limit": 1,
        },
        "run_policy": {
            "concurrency": 1,
            "model_retries": 0,
            "parser_validation_repairs": 0,
            "http_timeout_seconds": 60,
            "case_timeout_seconds": 90,
        },
        "prediction_status": "not_generated_at_freeze_time",
    }
    write_json(FREEZE_PATH, freeze)
    print(f"v38 random-dev5 frozen manifest={sha256(MANIFEST_PATH)}")


if __name__ == "__main__":
    main()
