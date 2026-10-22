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
    "m11-ai-campus-manifest-core-v36-dev4-comparison-v1-2026-09-03.json"
)
LABEL_PATH = Path("datasets/ai_campus_v34_dev4_label_freeze_v1_2026_09_03.json")
MANIFEST_PATH = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v37-dev4-comparison-v1-2026-09-03.json"
)
FREEZE_PATH = Path("datasets/ai_campus_v37_execution_freeze_v1_2026_09_03.json")
FROZEN_AT = "2026-09-03T10:45:03+08:00"

PARSER_FILES = (
    Path("src/config.py"),
    Path("src/services/core_jd_parser.py"),
    Path("src/domain/core_skill_semantics.py"),
    Path("src/domain/skill_normalizer.py"),
    Path("src/domain/job.py"),
    Path("src/infrastructure/llm_client.py"),
    Path("scripts/run_core_v37_evaluation.py"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def write_json(path: Path, payload: dict[str, Any], *, immutable: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"refusing to overwrite changed freeze: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def build_manifest() -> dict[str, Any]:
    source = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload = copy.deepcopy(source)
    payload["manifest_version"] = "m11-ai-campus-v37-dev4-comparison-v1"
    payload["dataset_version"] = "m11-ai-v37-dev4-comparison-v1-2026-09-03"
    payload["purpose"] = (
        "Run Parser v37 once on the same four frozen public JDs after generic "
        "qualification-heading and non-required any_of compatibility fixes."
    )
    payload["source_policy"] = (
        "Reuse the exact v34 frozen public JD inputs and owner-reviewed labels. "
        "Send each JD once; do not overwrite v34, v35, or v36 artifacts."
    )
    for case in payload["cases"]:
        case["source"]["authorization"] = (
            "User requested that fixes be evaluated on these same four public JDs "
            "on 2026-09-03."
        )
        case["input"]["scenario"] = "v37_same_four_frozen_label_comparison"
        tags = case["expected"].setdefault("tags", [])
        if "v37_same_four_comparison" not in tags:
            tags.append("v37_same_four_comparison")
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
        raise ValueError("runtime parser contract no longer matches the v37 freeze")

    write_json(MANIFEST_PATH, build_manifest(), immutable=True)
    freeze = {
        "freeze_version": "ai-campus-v37-execution-freeze-v1-2026-09-03",
        "frozen_at": FROZEN_AT,
        "purpose": "one v37 same-four public JD comparison",
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
        "labels": file_record(LABEL_PATH),
        "comparison_manifest": file_record(MANIFEST_PATH),
        "v36_result_basis": {
            "predictions": file_record(
                Path(
                    "artifacts/evaluation/"
                    "m11-ai-campus-predictions-core-v36-dev4-comparison-v1-api-"
                    "2026-09-03.json"
                )
            ),
            "valid_predictions": 2,
            "structured_output_invalid_cases": 2,
            "all_case_macro_f1": 0.38585858585858585,
        },
        "generic_changes": [
            "recognize 任职资格, 职位资格, and 岗位资格 as requirement headings",
            "downgrade non-required any_of clauses to ordinary all_of enumerations",
        ],
        "api_authorization": {
            "authorized_at": "2026-09-03",
            "destination": "configured DeepSeek API",
            "same_four_run_limit": 1,
        },
        "run_policy": {
            "concurrency": 1,
            "model_retries": 0,
            "parser_validation_repairs": 0,
            "http_timeout_seconds": 60,
            "case_timeout_seconds": 90,
            "checkpoint_resume": False,
            "retry_failures": False,
        },
        "prediction_status": "not_generated_at_freeze_time",
    }
    write_json(FREEZE_PATH, freeze, immutable=True)
    print(
        f"v37 frozen manifest={sha256(MANIFEST_PATH)} "
        f"labels={sha256(LABEL_PATH)}"
    )


if __name__ == "__main__":
    main()
