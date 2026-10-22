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
PRIOR_SELECTION_PATH = Path(
    "datasets/ai_campus_v37_random_dev5_selection_2026_09_03.json"
)
SELECTION_PATH = Path(
    "datasets/ai_campus_v39_other_dev5_selection_2026_09_03.json"
)
MANIFEST_PATH = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v39-other-dev5-v1-2026-09-03.json"
)
FREEZE_PATH = Path(
    "datasets/ai_campus_v39_other_dev5_execution_freeze_v1_2026_09_03.json"
)
SEED = "v39-other-dev5-2026-09-03"
FROZEN_AT = "2026-09-03T15:08:32.3039746+08:00"
POSITIVE_COUNT = 3
NEGATIVE_COUNT = 2

PARSER_FILES = (
    Path("src/config.py"),
    Path("src/services/core_jd_parser.py"),
    Path("src/domain/core_skill_semantics.py"),
    Path("src/domain/skill_normalizer.py"),
    Path("src/domain/job.py"),
    Path("src/infrastructure/llm_client.py"),
    Path("src/evaluation/models.py"),
    Path("src/evaluation/predict.py"),
    Path("scripts/run_core_v39_other_dev5.py"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rank_case(case_id: str) -> str:
    return hashlib.sha256(f"{SEED}|{case_id}".encode()).hexdigest()


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


def select_cases(source: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    prior = json.loads(PRIOR_SELECTION_PATH.read_text(encoding="utf-8"))
    excluded_ids = {case["id"] for case in prior["cases"]}
    candidates = [case for case in source["cases"] if case["id"] not in excluded_ids]
    positives = sorted(
        (
            case
            for case in candidates
            if case["expected"]["fields"].get("required_skill_groups")
        ),
        key=lambda case: rank_case(case["id"]),
    )[:POSITIVE_COUNT]
    negatives = sorted(
        (
            case
            for case in candidates
            if not case["expected"]["fields"].get("required_skill_groups")
        ),
        key=lambda case: rank_case(case["id"]),
    )[:NEGATIVE_COUNT]
    selected = [
        *(("any_of_positive", case) for case in positives),
        *(("any_of_negative", case) for case in negatives),
    ]
    selected_ids = [case["id"] for _, case in selected]
    expected_ids = [
        "campus-ai-032",
        "campus-ai-037",
        "campus-ai-121",
        "campus-ai-011",
        "campus-ai-128",
    ]
    if selected_ids != expected_ids:
        raise ValueError(f"stratified selection drifted: {selected_ids}")
    return selected


def build_selection(
    selected: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "version": "ai-campus-v39-other-dev5-selection-v1-2026-09-03",
        "status": "non_blind_development_stability_sample",
        "sampling_method": (
            "exclude prior random dev-5; split by expected any_of presence; "
            "select three positives and two negatives by ascending "
            "SHA-256(seed|case_id)"
        ),
        "seed": SEED,
        "population": "human-reviewed remaining51 dev-21 excluding prior dev-5",
        "population_size": 16,
        "sample_size": 5,
        "strata": {"any_of_positive": 3, "any_of_negative": 2},
        "sealed_holdout_included": False,
        "unseen_claimed": False,
        "source_manifest": file_record(SOURCE_MANIFEST_PATH),
        "excluded_prior_selection": file_record(PRIOR_SELECTION_PATH),
        "cases": [
            {
                "id": case["id"],
                "stratum": stratum,
                "rank_hash": rank_case(case["id"]),
                "source_url": case["input"].get("source_url"),
                "raw_content_sha256": content_sha256(case["input"]["raw_content"]),
            }
            for stratum, case in selected
        ],
    }


def build_manifest(
    source: dict[str, Any],
    selected: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    payload = copy.deepcopy(source)
    payload["manifest_version"] = "m11-ai-campus-v39-other-dev5-v1"
    payload["dataset_version"] = "m11-ai-v39-other-dev5-v1-2026-09-03"
    payload["purpose"] = (
        "Pre-registered non-blind development stability check for Parser v39 "
        "on five cases excluded from the prior random dev-5."
    )
    payload["source_policy"] = (
        "Use five human-reviewed public development JDs selected before "
        "prediction. This is not a sealed holdout or unseen evaluation."
    )
    payload["cases"] = [copy.deepcopy(case) for _, case in selected]
    for case in payload["cases"]:
        case["source"]["authorization"] = (
            "User requested verification on other non-blind public dev JDs on "
            "2026-09-03."
        )
        case["input"]["scenario"] = "v39_other_dev5_stability"
        tags = case["expected"].setdefault("tags", [])
        if "v39_other_dev5" not in tags:
            tags.append("v39_other_dev5")
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
        "jd-core-parser-v39",
        "jd-core-parser-prompt-v24",
        "core-job-fields-v10",
        "skill-ontology-v5",
        4096,
    )
    if actual_contract != expected_contract:
        raise ValueError("runtime parser contract no longer matches Parser v39")

    source = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    selected = select_cases(source)
    write_json(SELECTION_PATH, build_selection(selected))
    write_json(MANIFEST_PATH, build_manifest(source, selected))
    freeze = {
        "freeze_version": "ai-campus-v39-other-dev5-execution-freeze-v1",
        "frozen_at": FROZEN_AT,
        "purpose": "one Parser v39 other-dev5 stability run",
        "frozen_contract": {
            "parser": DEFAULT_CORE_PARSER_VERSION,
            "prompt": DEFAULT_CORE_PROMPT_VERSION,
            "schema": CORE_SCHEMA_VERSION,
            "skill_ontology": SKILL_ONTOLOGY_VERSION,
            "provider": "openai_compatible",
            "model": "deepseek-v4-flash",
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
            "public_jd_count": 5,
            "run_limit": 1,
        },
        "run_policy": {
            "concurrency": 1,
            "model_retries": 0,
            "parser_validation_repairs": 0,
            "http_timeout_seconds": 60,
            "case_timeout_seconds": 90,
            "failed_case_reruns": 0,
        },
        "evaluation_scope": {
            "sample_kind": "non_blind_development_stability_sample",
            "prior_random_dev5_excluded": True,
            "sealed_holdout_included": False,
            "unseen_claimed": False,
        },
        "prediction_status": "not_generated_at_freeze_time",
    }
    write_json(FREEZE_PATH, freeze)
    print(
        "v39 other-dev5 frozen cases="
        + ",".join(case["id"] for _, case in selected)
        + f" manifest={sha256(MANIFEST_PATH)}"
    )


if __name__ == "__main__":
    main()
