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
    "m11-ai-campus-manifest-core-v38-random-dev5-v1-2026-09-03.json"
)
SELECTION_PATH = Path(
    "datasets/ai_campus_v37_random_dev5_selection_2026_09_03.json"
)
MANIFEST_PATH = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v39-random-dev5-v1-2026-09-03.json"
)
FREEZE_PATH = Path(
    "datasets/ai_campus_v39_random_dev5_execution_freeze_v1_2026_09_03.json"
)
FROZEN_AT = "2026-09-03T14:52:46.9827359+08:00"

PARSER_FILES = (
    Path("src/config.py"),
    Path("src/services/core_jd_parser.py"),
    Path("src/domain/core_skill_semantics.py"),
    Path("src/domain/skill_normalizer.py"),
    Path("src/domain/job.py"),
    Path("src/infrastructure/llm_client.py"),
    Path("src/evaluation/models.py"),
    Path("src/evaluation/predict.py"),
    Path("scripts/run_core_v39_random_dev5.py"),
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
    payload["manifest_version"] = "m11-ai-campus-v39-random-dev5-v1"
    payload["dataset_version"] = "m11-ai-v39-random-dev5-v1-2026-09-03"
    payload["purpose"] = (
        "Compare Parser v39 on the exact v38 random dev-5 sample after generic "
        "skill-boundary, any-of recall, qualifier-scope, and ontology updates."
    )
    payload["source_policy"] = (
        "Reuse the exact reproducibly sampled five public dev JDs and frozen "
        "human-reviewed labels. This is a development comparison, not an "
        "unseen evaluation."
    )
    for case in payload["cases"]:
        case["source"]["authorization"] = (
            "User explicitly authorized sending these five public JDs to the "
            "configured DeepSeek API once on 2026-09-03."
        )
        case["input"]["scenario"] = "v39_same_random_dev5_comparison"
        tags = case["expected"].setdefault("tags", [])
        if "v39_same_random_dev5" not in tags:
            tags.append("v39_same_random_dev5")
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

    manifest = build_manifest()
    source = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    source_ids = [case["id"] for case in source["cases"]]
    manifest_ids = [case["id"] for case in manifest["cases"]]
    if manifest_ids != source_ids or len(manifest_ids) != 5:
        raise ValueError("v39 must preserve the exact v38 random dev-5 cases")

    write_json(MANIFEST_PATH, manifest)
    freeze = {
        "freeze_version": "ai-campus-v39-random-dev5-execution-freeze-v1",
        "frozen_at": FROZEN_AT,
        "purpose": "one Parser v39 same-random-dev5 development comparison",
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
        "source_manifest": file_record(SOURCE_MANIFEST_PATH),
        "manifest": file_record(MANIFEST_PATH),
        "v38_baseline": {
            "predictions": file_record(
                Path(
                    "artifacts/evaluation/"
                    "m11-ai-campus-predictions-core-v38-random-dev5-v1-api-"
                    "2026-09-03.json"
                )
            ),
            "report": file_record(
                Path(
                    "artifacts/evaluation/"
                    "m11-ai-campus-report-core-v38-random-dev5-v1-api-"
                    "2026-09-03.json"
                )
            ),
            "valid_predictions": 5,
            "five_field_macro_f1": 0.7255381604696673,
            "skill_detection_f1": 0.5934065934065934,
            "skill_concept_f1": 0.6029411764705882,
            "skill_concept_strength_macro_f1": 0.611466585927907,
            "any_of_positive_accuracy": 0.3333333333333333,
            "any_of_false_group_rate": 0.0,
            "qualifier_f1": 0.1111111111111111,
        },
        "generic_changes": [
            "filter generic responsibility actions, business objects, and results",
            "recover source-explicit direct-or and counted-example any_of groups",
            "require source-explicit experience scope for qualifiers",
            "normalize inference-engine categories through skill ontology v5",
        ],
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
            "sample_kind": "development_regression_sample",
            "sealed_holdout_included": False,
            "unseen_claimed": False,
        },
        "prediction_status": "not_generated_at_freeze_time",
    }
    write_json(FREEZE_PATH, freeze)
    print(
        f"v39 random-dev5 frozen cases={','.join(manifest_ids)} "
        f"manifest={sha256(MANIFEST_PATH)}"
    )


if __name__ == "__main__":
    main()
