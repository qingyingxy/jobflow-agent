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
    "m11-ai-campus-manifest-core-v20-label-v14-remaining51-dev21-strict-"
    "2026-09-02.json"
)
SELECTION_PATH = Path(
    "datasets/ai_campus_v37_random_dev5_selection_2026_09_03.json"
)
MANIFEST_PATH = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v37-random-dev5-v1-2026-09-03.json"
)
FREEZE_PATH = Path(
    "datasets/ai_campus_v37_random_dev5_execution_freeze_v1_2026_09_03.json"
)
SEED = "v37-random-dev5-2026-09-03"
SAMPLE_SIZE = 5
FROZEN_AT = "2026-09-03T11:02:00+08:00"

PARSER_FILES = (
    Path("src/config.py"),
    Path("src/services/core_jd_parser.py"),
    Path("src/domain/core_skill_semantics.py"),
    Path("src/domain/skill_normalizer.py"),
    Path("src/domain/job.py"),
    Path("src/infrastructure/llm_client.py"),
    Path("scripts/run_core_v37_random_dev5.py"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def rank_case(case_id: str) -> str:
    return hashlib.sha256(f"{SEED}|{case_id}".encode()).hexdigest()


def selected_cases(source: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = sorted(source["cases"], key=lambda case: rank_case(case["id"]))
    return ranked[:SAMPLE_SIZE]


def build_selection(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "ai-campus-v37-random-dev5-selection-v1-2026-09-03",
        "status": "development_regression_sample",
        "sampling_method": "ascending SHA-256(seed|case_id)",
        "seed": SEED,
        "population": "human-reviewed remaining51 dev-21",
        "population_size": 21,
        "sample_size": SAMPLE_SIZE,
        "sealed_holdout_included": False,
        "unseen_claimed": False,
        "source_manifest": file_record(SOURCE_MANIFEST_PATH),
        "cases": [
            {
                "id": case["id"],
                "rank_hash": rank_case(case["id"]),
                "source_url": case["input"].get("source_url"),
                "raw_content_sha256": content_sha256(case["input"]["raw_content"]),
            }
            for case in cases
        ],
    }


def build_manifest(
    source: dict[str, Any],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload["manifest_version"] = "m11-ai-campus-v37-random-dev5-v1"
    payload["dataset_version"] = "m11-ai-v37-random-dev5-v1-2026-09-03"
    payload["purpose"] = (
        "Reproducible random five-case Parser v37 regression smoke over the "
        "human-reviewed dev-21 population."
    )
    payload["source_policy"] = (
        "Use five public JDs sampled from the non-holdout development split. "
        "This is not an unseen or final evaluation."
    )
    payload["cases"] = copy.deepcopy(cases)
    for case in payload["cases"]:
        case["source"]["authorization"] = (
            "User requested a random sample from the current public JD dataset "
            "for Parser evaluation on 2026-09-03."
        )
        case["input"]["scenario"] = "v37_random_dev5_regression"
        tags = case["expected"].setdefault("tags", [])
        if "v37_random_dev5" not in tags:
            tags.append("v37_random_dev5")
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
        "jd-core-parser-v37",
        "jd-core-parser-prompt-v23",
        "core-job-fields-v10",
        "skill-ontology-v4",
        4096,
    )
    if actual_contract != expected_contract:
        raise ValueError("runtime parser contract no longer matches Parser v37")

    source = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    cases = selected_cases(source)
    write_json(SELECTION_PATH, build_selection(cases))
    write_json(MANIFEST_PATH, build_manifest(source, cases))
    freeze = {
        "freeze_version": "ai-campus-v37-random-dev5-execution-freeze-v1",
        "frozen_at": FROZEN_AT,
        "purpose": "one Parser v37 random dev-5 regression run",
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
        "api_authorization": {
            "authorized_at": "2026-09-03",
            "destination": "configured DeepSeek API",
            "public_jd_count": SAMPLE_SIZE,
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
    print(
        f"selected={','.join(case['id'] for case in cases)} "
        f"manifest={sha256(MANIFEST_PATH)}"
    )


if __name__ == "__main__":
    main()
